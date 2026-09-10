import json

from tradingagents.dataflows import kr_ticker_directory as directory
from tradingagents.dataflows.kr_tickers import resolve_kr_ticker, search_kr_tickers
from tradingagents.screener.universe import parse_naver_market_sum


def _use(tmp_path, monkeypatch, items):
    path = tmp_path / "kr_tickers.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(directory, "DIRECTORY_PATH", path)
    directory.load_directory.cache_clear()
    return path


def test_directory_search_ranks_code_then_name(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, [
        {"code": "034020", "name": "두산에너빌리티", "market": "KOSPI"},
        {"code": "000150", "name": "두산", "market": "KOSPI"},
        {"code": "241560", "name": "두산밥캣", "market": "KOSPI"},
        {"code": "005930", "name": "삼성전자", "market": "KOSPI"},
        {"code": "005935", "name": "삼성전자우", "market": "KOSPI"},
        {"code": "bad", "name": "x", "market": "KOSDAQ"},
    ])
    assert directory.directory_size() == 5
    assert [e.name for e in directory.search_directory("두산")] == ["두산", "두산밥캣", "두산에너빌리티"]
    assert [e.code for e in directory.search_directory("0059")] == ["005930", "005935"]
    assert [e.code for e in directory.search_directory("005930")] == ["005930"]
    assert [e.name for e in directory.search_directory("에너빌")] == ["두산에너빌리티"]
    assert directory.search_directory("   ") == [] and directory.search_directory("없는회사") == []
    assert directory.lookup_directory("241560").name == "두산밥캣"


def test_search_and_resolve_use_directory_without_pykrx(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, [{"code": "034020", "name": "두산에너빌리티", "market": "KOSPI"}, {"code": "196170", "name": "알테오젠", "market": "KOSDAQ"}])
    found = search_kr_tickers("두산", limit=5, lookup_pykrx=False)
    assert [(t.code, t.market) for t in found] == [("034020", "KOSPI")]
    resolved = resolve_kr_ticker("196170", lookup_pykrx=False)
    assert resolved.name == "알테오젠" and resolved.market == "KOSDAQ" and resolved.yfinance_symbol == "196170.KQ"
    assert search_kr_tickers("삼성", limit=3, lookup_pykrx=False)[0].code == "005930"  # built-in seed still first


def test_write_directory_dedupes_and_sorts(tmp_path, monkeypatch):
    path = tmp_path / "out.json"
    monkeypatch.setattr(directory, "DIRECTORY_PATH", path)
    directory.write_directory([
        directory.DirectoryEntry("005930", "삼성전자", "KOSPI"),
        {"code": "000660", "name": "SK하이닉스", "market": "KOSPI"},
        {"code": "005930", "name": "dup", "market": "KOSPI"},
    ], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [i["code"] for i in payload["items"]] == ["000660", "005930"] and payload["count"] == 2
    assert directory.directory_size() == 2


def test_naver_parser_can_keep_etfs_for_the_directory():
    headers = ("N", "종목명", "현재가", "전일비", "등락률", "액면가", "시가총액", "상장주식수", "외국인비율", "거래량", "PER", "ROE", "토론")
    head = "".join(f"<th>{h}</th>" for h in headers)
    rows = [("069500", "KODEX 200", "35,000", "0", "1,000,000"), ("005930", "삼성전자", "70,000", "100", "5,000,000")]
    body = "".join(f'<tr><td>{i}</td><td><a href="/item/main.naver?code={c}">{n}</a></td><td>{p}</td><td>상승 1</td><td>+0.10%</td><td>{pv}</td><td>10</td><td>1</td><td>1</td><td>1,000</td><td>10</td><td>1</td><td></td></tr>' for i, (c, n, p, pv, _) in enumerate(rows, 1))
    html = f'<html><table class="type_2"><tr>{head}</tr>{body}</table></html>'
    assert [r.code for r in parse_naver_market_sum(html, "KOSPI")] == ["005930"]
    assert [r.code for r in parse_naver_market_sum(html, "KOSPI", include_non_equity=True)] == ["069500", "005930"]
