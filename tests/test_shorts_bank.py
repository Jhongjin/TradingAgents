"""Which story the channel tells today, and why it does not repeat itself."""

import json
from datetime import date, datetime, timezone

import pytest

from tradingagents.shorts.bank import (
    BY_KEY,
    STORIES,
    evaluate,
    plan,
    read_ledger,
    record_published,
)

FRIDAY = datetime(2026, 9, 11, 2, 0, tzinfo=timezone.utc)     # 11:00 KST, a Friday
MONDAY = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)     # and the Monday after


def _payload(*, exits: tuple = (), closed_before: int = 0, entered_today: int = 0, today: str = "2026-09-14") -> dict:
    closed = [
        {"ticker_name": f"과거{index}", "realized_return": -0.02, "exit_reason": "stop_loss",
         "exit_date": "2026-09-01", "entry_date": "2026-08-28"}
        for index in range(closed_before)
    ]
    for name, value, reason in exits:
        closed.append({"ticker_name": name, "realized_return": value, "exit_reason": reason,
                       "exit_date": today, "entry_date": "2026-09-10"})
    return {
        "summary": {"initial_cash": 1.5e8, "total_return": -0.0117, "closed_count": len(closed), "win_count": 0},
        "accounts": [
            {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.0147, "open_count": 3, "closed_count": 3}},
            {"key": "rules", "label": "규칙 전용", "summary": {"total_return": -0.0205, "open_count": 6, "closed_count": 2}},
        ],
        "positions": [{"ticker_name": f"보유{index}", "account": "paper", "entry_date": today}
                      for index in range(entered_today)],
        "closed": closed,
    }


def test_a_day_where_stops_fired_beats_a_day_where_nothing_did():
    quiet = plan(_payload(closed_before=4, entered_today=3), now=MONDAY, ledger=[])
    loud = plan(_payload(closed_before=4, entered_today=3, exits=(("티에스이", -0.156, "stop_loss"),)), now=MONDAY, ledger=[])

    assert quiet["story"] in {"record", "picks"}
    assert loud["story"] == "stop_worked"
    # the same account, one event, and the whole running order changes
    assert loud["candidates"][0]["score"] > quiet["candidates"][0]["score"]
    assert "손절선에서 1건" in loud["reason"]


def test_a_bigger_loss_scores_higher_than_a_smaller_one():
    small = evaluate(_payload(exits=(("가", -0.03, "stop_loss"),)), now=MONDAY, ledger=[])
    large = evaluate(_payload(exits=(("나", -0.16, "stop_loss"),)), now=MONDAY, ledger=[])
    by_key = lambda rows: {row.story.key: row.score for row in rows}
    assert by_key(large)["stop_worked"] > by_key(small)["stop_worked"]


def test_a_story_told_yesterday_is_no_longer_new():
    payload = _payload(closed_before=4, exits=(("티에스이", -0.156, "stop_loss"),))
    fresh = plan(payload, now=MONDAY, ledger=[])
    assert fresh["story"] == "stop_worked"

    repeated = plan(payload, now=MONDAY, ledger=[{"story": "stop_worked", "date": "2026-09-13"}])
    assert repeated["story"] != "stop_worked"           # it ran yesterday, so something else goes out
    scores = {item["key"]: item["novelty"] for item in repeated["candidates"]}
    assert scores["stop_worked"] < 1.0

    # and once the cooldown has passed it is new again
    rested = plan(payload, now=MONDAY, ledger=[{"story": "stop_worked", "date": "2026-09-01"}])
    assert rested["story"] == "stop_worked"


def test_standby_material_is_always_in_the_running_and_never_wins_a_loud_day():
    rows = {item.story.key: item for item in evaluate(_payload(), now=MONDAY, ledger=[])}
    assert {"explain_stop", "explain_debate", "explain_open"} <= set(rows)
    assert all(rows[key].story.tier == "standby" for key in ("explain_stop", "explain_debate", "explain_open"))

    loud = evaluate(_payload(closed_before=4, exits=(("가", -0.16, "stop_loss"),)), now=MONDAY, ledger=[])
    assert loud[0].story.tier != "standby"


def test_friday_puts_the_weekly_report_in_the_running_once_there_is_a_line_to_draw():
    from tradingagents.shorts.bank import MIN_CURVE_DAYS

    drawable = {**_payload(), "curve": {"points": [{"date": f"d{i}"} for i in range(MIN_CURVE_DAYS)]}}
    friday = {item["key"] for item in plan(drawable, now=FRIDAY, ledger=[])["candidates"]}
    monday = {item["key"] for item in plan(drawable, now=MONDAY, ledger=[])["candidates"]}
    assert "weekly" in friday and "weekly" not in monday

    # two points is a line segment, not a curve, so the cut waits
    thin = {**_payload(), "curve": {"points": [{"date": "d0"}, {"date": "d1"}]}}
    assert "weekly" not in {item["key"] for item in plan(thin, now=FRIDAY, ledger=[])["candidates"]}


def test_a_milestone_fires_only_on_the_round_number():
    fired = lambda count: {item.story.key for item in evaluate(_payload(closed_before=count), now=MONDAY, ledger=[])}
    assert "milestone" in fired(10) and "milestone" in fired(25)
    assert "milestone" not in fired(11) and "milestone" not in fired(9)


def test_only_a_story_that_can_actually_be_drawn_is_chosen():
    decision = plan(_payload(closed_before=4, exits=(("가", -0.02, "take_profit"),)), now=MONDAY, ledger=[])
    chosen = BY_KEY[decision["story"]]
    assert chosen.renderable and decision["renderer"] in {"record", "picks", "debate"}
    # take_profit fired and scored well, but nothing draws it yet, so it waits
    assert "take_profit" in {item["key"] for item in decision["candidates"]}
    assert "take_profit" in decision["waiting"]


def test_an_empty_account_still_yields_a_decision():
    decision = plan({"summary": {}, "accounts": [], "closed": [], "positions": []}, now=MONDAY, ledger=[])
    assert decision["candidates"]                        # the shelf is never empty
    assert decision["story"] is None                     # but nothing renderable fired
    assert "만들 수 있는 것이 없습니다" in decision["reason"]


def test_the_ledger_remembers_what_went_out(tmp_path):
    path = tmp_path / "published.json"
    assert read_ledger(path) == []

    row = record_published("record", video_id="abc123", when=date(2026, 9, 14), path=path)
    assert row["story"] == "record" and row["video_id"] == "abc123"
    record_published("picks", when=date(2026, 9, 15), path=path)

    rows = read_ledger(path)
    assert [item["story"] for item in rows] == ["record", "picks"]
    assert json.loads(path.read_text(encoding="utf-8"))[0]["date"] == "2026-09-14"

    path.write_text("not json", encoding="utf-8")
    assert read_ledger(path) == []                       # a damaged ledger is not a crash


def test_every_story_declares_what_it_needs():
    assert len({story.key for story in STORIES}) == len(STORIES)
    for story in STORIES:
        assert story.tier in {"daily", "event", "periodic", "standby"}
        assert 0 < story.completeness <= 1 and story.cooldown_days >= 1
        assert story.renderer in {None, "record", "picks", "debate", "curve", "candles"}
    from tradingagents.shorts.stories import STORIES as BUILDERS
    # every renderer a story names must have something that draws it
    assert {story.renderer for story in STORIES if story.renderer} <= set(BUILDERS)
    assert any(story.renderable for story in STORIES)
    assert any(not story.renderable for story in STORIES)   # the plan is honest about what is unbuilt


def test_both_workflows_are_importable_and_ship_no_secrets():
    """The files handed to n8n: wired end to end, every credential left blank."""

    import json as _json
    from pathlib import Path

    for name in ("daily-short-hosted.json", "daily-short-local.json"):
        flow = _json.loads(Path("automation/n8n", name).read_text(encoding="utf-8"))
        names = {node["name"] for node in flow["nodes"]}
        assert flow["settings"]["timezone"] == "Asia/Seoul"      # 08:40 has to mean 08:40 in Seoul

        # every connection points at a node that exists
        for source, wiring in flow["connections"].items():
            assert source in names, f"{name}: {source}"
            for branch in wiring["main"]:
                for link in branch:
                    assert link["node"] in names, f"{name}: {link['node']}"

        credentials = [value for node in flow["nodes"] for value in (node.get("credentials") or {}).values()]
        assert credentials, f"{name}: 자격증명 슬롯이 없습니다"
        assert all(item["id"] == "" and item["name"] == "" for item in credentials)
        assert "youTube" in {node["type"].rsplit(".", 1)[-1] for node in flow["nodes"]}

        blob = _json.dumps(flow, ensure_ascii=False)
        for leak in ("sk-", "AIza", "ya29.", "bot1", "password"):
            assert leak not in blob, f"{name}: {leak}"

    hosted = _json.loads(Path("automation/n8n/daily-short-hosted.json").read_text(encoding="utf-8"))
    webhook = next(node for node in hosted["nodes"] if node["type"].endswith("webhook"))
    assert webhook["parameters"]["authentication"] == "headerAuth"   # the ear is not left open
    assert webhook["parameters"]["httpMethod"] == "POST"

    # the model that only rewrites titles ships switched off
    local = _json.loads(Path("automation/n8n/daily-short-local.json").read_text(encoding="utf-8"))
    model = next(node for node in local["nodes"] if "openAi" in node["type"])
    assert model.get("disabled") is True

    # the file reaches YouTube under "data", the binary name every n8n node
    # reads by default, so that node needs no editing after import
    reader = next(node for node in local["nodes"] if node["type"].endswith("readWriteFile"))
    assert reader["parameters"]["options"]["dataPropertyName"] == "data"
    # and it finds that file whatever n8n called it, because the key depends on
    # the version: 'video', 'video0', or the multipart field name
    handoff = next(node for node in hosted["nodes"] if node["name"] == "받은 것 확인")
    code = handoff["parameters"]["jsCode"]
    assert "binary: { data: file }" in code
    assert "Object.keys(binary)" in code and "binary.video" not in code
    for flow in (hosted, local):
        upload = next(node for node in flow["nodes"] if node["type"].endswith("youTube"))
        assert "binaryProperty" not in _json.dumps(upload["parameters"])   # the default is left alone


def test_an_upload_that_returns_no_id_stops_the_flow_instead_of_announcing_it():
    """The morning the chain ran to the end and the channel stayed empty."""

    import json as _json
    from pathlib import Path

    flow = _json.loads(Path("automation/n8n/daily-short-hosted.json").read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in flow["nodes"]}
    check = nodes["업로드 확인"]

    # it throws, so 실패 감지 picks it up and the alert carries what YouTube said
    assert "throw new Error" in check["parameters"]["jsCode"]
    assert "JSON.stringify(up)" in check["parameters"]["jsCode"]
    assert check.get("onError") is None                  # continuing would defeat the point

    # and it sits between the upload and everything that announces a success
    assert flow["connections"]["유튜브 업로드"]["main"][0][0]["node"] == "업로드 확인"
    for name in ("채널 댓글", "텔레그램 알림", "업로드 결과 회신"):
        blob = _json.dumps(nodes[name]["parameters"], ensure_ascii=False)
        assert "$('업로드 확인').first().json.videoId" in blob, name
        assert "$('유튜브 업로드')" not in blob, name     # the unchecked id is gone


def test_the_upload_flow_posts_a_comment_and_says_what_it_cannot_do():
    """A pinned comment is half automatable: the API posts, Studio pins."""

    import json as _json
    from pathlib import Path

    flow = _json.loads(Path("automation/n8n/daily-short-hosted.json").read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in flow["nodes"]}

    comment = nodes["채널 댓글"]
    assert comment["parameters"]["url"] == "https://www.googleapis.com/youtube/v3/commentThreads"
    # the same credential as the upload: n8n's YouTube scopes already carry force-ssl
    assert comment["parameters"]["nodeCredentialType"] == "youTubeOAuth2Api"
    assert comment["credentials"]["youTubeOAuth2Api"] == {"id": "", "name": ""}
    # a failed comment must never lose a finished upload
    assert comment["onError"] == "continueRegularOutput"
    assert "고정" in comment["notes"] and "Studio" in comment["notes"]

    # and it sits between the checked upload and the notification
    assert flow["connections"]["업로드 확인"]["main"][0][0]["node"] == "채널 댓글"
    assert flow["connections"]["채널 댓글"]["main"][0][0]["node"] == "텔레그램 알림"

    # the text comes from the PC, which is where the story's own words are
    assert "$('받은 것 확인').first().json.comment" in comment["parameters"]["jsonBody"]
    assert "comment: String(body.comment" in nodes["받은 것 확인"]["parameters"]["jsCode"]

    # the operator is told to go and pin it, because nothing else will
    assert "Studio 에서 고정해 주세요" in nodes["텔레그램 알림"]["parameters"]["text"]


def test_the_comment_leads_with_the_receipts_and_lands_a_newcomer():
    from tradingagents.shorts.stories import build_record, site_url

    payload = {
        "summary": {"initial_cash": 1.5e8, "total_return": -0.0173, "closed_count": 8, "win_count": 0},
        "accounts": [{"key": "paper", "label": "AI 확인",
                      "summary": {"total_return": -0.0195, "open_count": 5, "closed_count": 3}}],
        "positions": [],
        "closed": [{"ticker_name": "티에스이", "realized_return": -0.156, "exit_reason": "stop_loss",
                    "exit_date": "2026-09-11", "entry_date": "2026-09-10"}],
    }
    comment = build_record(payload).comment
    lines = comment.splitlines()

    assert "8건" in lines[0]                              # what is on the other end
    assert lines[1].startswith(f"{site_url()}/paper?")     # and the link, before the fold
    assert "utm_source=youtube" in lines[1]
    assert any("/start?" in line for line in lines)        # for whoever arrived cold
    assert len(comment) < 500                              # nobody reads past this


def test_a_200_with_no_video_id_is_a_failure_not_a_footnote():
    """A morning went by with nothing published and the run said 업로드됨."""

    import inspect

    from cli import main as cli

    source = inspect.getsource(cli.shorts_daily_command)
    # the id is what proves YouTube saw the file; without it the run stops
    assert 'video_id = str(answer.get("videoId") or "").strip()' in source
    assert "업로드되지 않았습니다." in source
    assert source.index("업로드되지 않았습니다.") < source.index("record_published(")
    # and nothing is written to the ledger, so tomorrow does not skip the story
    assert source.count("record_published(") == 1


def test_each_cut_has_its_own_ground_so_the_grid_is_not_one_video_five_times():
    """Four cuts on one navy read as the same upload posted again."""

    import re
    from pathlib import Path

    grounds = {}
    for path in sorted(Path("tradingagents/shorts").glob("composition*.html")):
        found = re.search(r"html, body \{[^}]*background: (#[0-9a-f]{6})", path.read_text(encoding="utf-8"))
        assert found, path.name
        grounds[path.name] = found.group(1)

    assert len(grounds) >= 4
    assert len(set(grounds.values())) == len(grounds), grounds


def test_the_daily_path_draws_the_cut_the_story_named():
    """It drew compose_record whatever won, so a picks day looked like a loss day."""

    import inspect

    from cli import main as cli

    source = inspect.getsource(cli._shorts_build)
    assert '"debate": compose_debate' in source and '"curve": compose_curve' in source
    assert '"candles": compose_candles' in source
    assert "compose(payload, board)" in source
    # and the story, not just the cut, reaches the words under the video
    assert "build(renderer, payload, story=story_key)" in source


def test_three_stories_that_share_the_record_cut_do_not_share_its_title():
    """They went out as one title, so the channel read as a repost."""

    from datetime import datetime

    from tradingagents.shorts import build
    from tradingagents.shorts.bank import KST

    now = datetime(2026, 9, 16, 11, 0, tzinfo=KST)
    payload = {
        "summary": {"initial_cash": 1.5e8, "total_return": -0.0173, "closed_count": 8, "win_count": 0},
        "accounts": [],
        "positions": [],
        "closed": [
            {"ticker_name": "티에스이", "realized_return": -0.156, "exit_reason": "stop_loss",
             "exit_date": "2026-09-16", "entry_date": "2026-09-10"},
            {"ticker_name": "한올바이오", "realized_return": -0.081, "exit_reason": "stop_loss",
             "exit_date": "2026-09-16", "entry_date": "2026-09-11"},
        ],
    }
    titles = {key: build("record", payload, now=now, story=key).title
              for key in ("record", "exits", "stop_worked")}
    assert len(set(titles.values())) == 3, titles
    assert "티에스이" in titles["stop_worked"] and "-15.6%" in titles["stop_worked"]
    assert "2종목" in titles["exits"]
    # and the slug follows the story too, so renders do not overwrite each other
    assert build("record", payload, now=now, story="exits").slug.startswith("exits-")
