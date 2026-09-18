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

# What the stop-loss explainer quotes. Production loads these from
# backtest_runs; a topic whose evidence is missing stays off the shelf, which
# is asserted on its own below.
_BACKTESTS = {
    "rules:현행 5%/10%": {"total_return": 0.5033, "max_drawdown": -0.2887,
                          "sharpe_ratio": 0.620116, "hit_rate": 0.3915},
    "rules:변동성 제외 + 손절 8%": {"total_return": 1.2646, "max_drawdown": -0.2402,
                                   "sharpe_ratio": 1.156081, "hit_rate": 0.4912,
                                   "benchmark_return": 1.684, "start_date": "2023-09-19",
                                   "end_date": "2026-09-18"},
}

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
        "backtests": _BACKTESTS,
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

    # a quiet day now goes to an explainer or an account cut, never to
    # "nothing happened today"
    assert quiet["story"] in {"record", "picks", "funnel", "explain_stop", "explain_debate", "explain_open"}
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

    # and once the cooldown has passed it climbs back — but not all the way to
    # a story that has never run, which is what stops one cut owning the week
    rested = plan(payload, now=MONDAY, ledger=[{"story": "stop_worked", "date": "2026-09-01"}])
    by_key = {item["key"]: item["novelty"] for item in rested["candidates"]}
    assert 0.75 <= by_key["stop_worked"] < 1.0
    assert by_key["exits"] == 1.0                        # never told, so it goes first


def test_standby_material_is_always_in_the_running_and_never_wins_a_loud_day():
    rows = {item.story.key: item for item in evaluate(_payload(closed_before=4), now=MONDAY, ledger=[])}
    assert {"explain_stop", "explain_debate", "explain_open"} <= set(rows)
    assert all(rows[key].story.tier == "standby" for key in ("explain_stop", "explain_debate", "explain_open"))
    assert all(rows[key].story.renderable for key in ("explain_stop", "explain_debate", "explain_open"))

    loud = evaluate(_payload(closed_before=4, exits=(("가", -0.16, "stop_loss"),)), now=MONDAY, ledger=[])
    assert loud[0].story.tier != "standby"


def test_an_explainer_waits_until_its_evidence_beat_has_something_in_it():
    """Explaining the method and then showing an empty table is worse than a quiet day."""

    # nothing closed yet, so "we publish the losing ones too" has nothing to show
    fresh = {key: item for item in evaluate(_payload(), now=MONDAY, ledger=[]) for key in [item.story.key]}
    assert "explain_open" not in fresh
    assert "explain_stop" in fresh          # its proof is the stored backtest pair

    # and with no run stored, the stop explainer has nothing to show either —
    # its figures used to be constants, so it could always be drawn
    without = {**_payload(closed_before=4), "backtests": {}}
    assert "explain_stop" not in {item.story.key for item in evaluate(without, now=MONDAY, ledger=[])}

    # and one book on its own cannot show what the second book is for
    one_book = {**_payload(closed_before=4), "accounts": [
        {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.01, "open_count": 2, "closed_count": 1}}]}
    assert "explain_debate" not in {item.story.key for item in evaluate(one_book, now=MONDAY, ledger=[])}


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
    assert chosen.renderable and decision["renderer"] in {"record", "picks", "debate", "explain", "funnel"}
    # take_profit fired and scored well, but nothing draws it yet, so it waits
    assert "take_profit" in {item["key"] for item in decision["candidates"]}
    assert "take_profit" in decision["waiting"]


def test_an_empty_account_still_yields_a_video():
    """The first week has no trades, and the channel still has to post."""

    decision = plan({"summary": {}, "accounts": [], "closed": [], "positions": [],
                     "backtests": _BACKTESTS}, now=MONDAY, ledger=[])
    assert decision["candidates"]                        # the shelf is never empty
    # and now something on it can actually be drawn: the explainers do not need
    # an account at all, which is the whole point of holding a daily slot
    assert decision["story"] == "explain_stop"
    assert decision["renderer"] == "explain"


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
        # not a hand-kept list of names — the invariant is that whatever a
        # story names can actually be built, which is asserted below
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

    # It used to throw. Throwing killed the reply, so three mornings in a row
    # there was nothing to inspect — and the video was on the channel each
    # time. It hands the upload node's own output through instead.
    code = check["parameters"]["jsCode"]
    assert "throw new Error" not in code
    assert "findId" in code and "upload: up" in code

    # and it sits between the upload and everything that announces a success
    assert flow["connections"]["유튜브 업로드"]["main"][0][0]["node"] == "업로드 확인"
    for name in ("채널 댓글", "텔레그램 알림"):
        blob = _json.dumps(nodes[name]["parameters"], ensure_ascii=False)
        assert "$('업로드 확인').first().json.videoId" in blob, name
        assert "$('유튜브 업로드')" not in blob, name     # the unchecked id is gone

    # the reply carries the raw output so the PC can find the id itself
    reply = nodes["업로드 결과 회신"]["parameters"]["responseBody"]
    assert "$('업로드 확인').first().json.videoId" in reply
    assert "upload: $('유튜브 업로드').first().json" in reply


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
    assert "video_id = _video_id_in(answer)" in source
    assert "videoId 를 받지 못했습니다." in source
    assert "raise typer.Exit(code=1)" in source.split("videoId 를 받지 못했습니다.", 1)[1]


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


def test_the_screen_itself_is_a_story_and_it_beats_another_loss_report():
    """A channel that only reports its own losses gives nobody a reason to stay."""

    funnel = {
        "universe": 349,
        "stages": [
            {"label": "1차 선별", "from": 349, "to": 34},
            {"label": "예측 기준 미달", "from": 34, "to": 19},
            {"label": "AI 토론 탈락", "from": 19, "to": 7},
        ],
        "picks": [{"name": "티에스이", "sub": "비중 확대", "value": "0.62"}],
    }
    quiet = _payload(closed_before=6)
    rows = {item.story.key: item for item in evaluate({**quiet, "funnel": funnel}, now=MONDAY, ledger=[])}
    assert "funnel" in rows
    assert rows["funnel"].score > rows["record"].score      # the screen outranks the scoreboard
    assert plan({**quiet, "funnel": funnel}, now=MONDAY, ledger=[])["story"] == "funnel"

    # a run that threw almost nothing away is a formality, not a story
    thin = {**funnel, "universe": 40, "stages": [{"label": "1차 선별", "from": 40, "to": 38}]}
    assert "funnel" not in {item.story.key for item in evaluate({**quiet, "funnel": thin}, now=MONDAY, ledger=[])}


def test_the_funnel_is_read_off_the_run_s_own_stages_not_measured_again():
    from cli.main import _funnel_in

    run = {
        "run": {"as_of_date": "2026-09-16", "universe_size": 349, "candidate_count": 28},
        "decisions": (
            [{"stage": "forecast_rejected", "ticker_name": f"탈락{i}"} for i in range(15)]
            + [{"stage": "confirmation_rejected", "ticker_name": f"토론탈락{i}"} for i in range(10)]
            + [{"stage": "gate_rejected", "ticker_name": f"한도{i}"} for i in range(2)]
            + [{"stage": "ordered", "ticker_name": "티에스이", "ticker_code": "131290",
                "confirmation_rating": "overweight", "confirmation_confidence": 0.62,
                "forecast_expected_return": 0.042}]
        ),
    }
    found = _funnel_in(run)
    assert found["universe"] == 349
    # the screener's own work happens before any decision row exists, so it is
    # read off the header rather than counted from the decisions
    assert found["stages"][0] == {"label": "거래대금·밸류·변동성", "from": 349, "to": 28}
    assert [row["label"] for row in found["stages"][1:]] == ["예측 기준 미달", "AI 토론 탈락", "보유 한도 초과"]
    assert found["stages"][-1]["to"] == 1                    # what actually got bought
    assert found["picks"][0]["name"] == "티에스이"
    assert "비중 확대" in found["picks"][0]["sub"] and "+4.2%" in found["picks"][0]["sub"]
    assert found["picks"][0]["value"] == "0.62"

    # a rules-only run has no AI confidence, and the column shows the screener's
    # own score rather than sitting blank
    rules_only = _funnel_in({
        "run": {"universe_size": 349, "candidate_count": 20},
        "decisions": [{"stage": "ordered", "ticker_name": "JB금융지주", "composite_score": 3.0852,
                       "screener_rank": 1}] * 3,
    })
    assert [row["to"] for row in rules_only["stages"]] == [20, 3]
    assert rules_only["picks"][0]["value"] == "3.09점"
    assert "선별 1위" in rules_only["picks"][0]["sub"]

    # a run with no universe behind it draws nothing rather than a wrong funnel
    assert _funnel_in({"run": {"universe_size": 0}, "decisions": [{"stage": "ordered"}]}) is None
    # and neither does one where the screen threw nothing away
    assert _funnel_in({"run": {"universe_size": 20, "candidate_count": 20},
                       "decisions": [{"stage": "ordered"}] * 20}) is None


def test_every_topic_says_something_different_and_names_its_evidence():
    """Six cuts on one subject is the problem these were written to fix."""

    from datetime import datetime

    from tradingagents.shorts import build
    from tradingagents.shorts.bank import KST
    from tradingagents.shorts.topics import BASELINE_LABEL, CHANGED_LABEL, TOPICS

    now = datetime(2026, 9, 16, 8, 40, tzinfo=KST)
    payload = {
        "summary": {"initial_cash": 1.5e8, "total_return": -0.0173, "closed_count": 8, "win_count": 1},
        "accounts": [
            {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.0147, "open_count": 7, "closed_count": 4}},
            {"key": "rules", "label": "규칙 전용", "summary": {"total_return": -0.0205, "open_count": 6, "closed_count": 4}},
        ],
        "closed": [{"ticker_name": f"정리{i}", "realized_return": -0.05, "exit_date": "2026-09-10"} for i in range(8)],
        "positions": [],
        "backtests": {
            BASELINE_LABEL: {"total_return": 0.5033, "max_drawdown": -0.2887,
                             "sharpe_ratio": 0.620116, "hit_rate": 0.3915},
            CHANGED_LABEL: {"total_return": 1.2646, "max_drawdown": -0.2402,
                            "sharpe_ratio": 1.156081, "hit_rate": 0.4912,
                            "benchmark_return": 1.684, "start_date": "2023-09-19",
                            "end_date": "2026-09-18"},
        },
    }

    boards = {topic.key: build("explain", payload, now=now, story=topic.key) for topic in TOPICS}
    assert len({board.title for board in boards.values()}) == len(TOPICS)
    assert len({board.slug for board in boards.values()}) == len(TOPICS)
    for topic in TOPICS:
        board = boards[topic.key]
        assert len(board.scenes) == 4 and board.seconds > 15
        # the evidence beat is never empty for a topic that reached the shelf
        assert board.scenes[2].rows, topic.key
        assert board.comment and topic.path in board.description

    # the one topic whose proof is a backtest reads it off the stored runs
    note = boards["explain_stop"].scenes[2].note
    assert "2023-09-19~2026-09-18 백테스트" in note
    assert "손절 5%→8%, 변동성 상위 20% 제외" in note

    # and the two that read the live account did read it
    assert any("−2.05%" in str(row.get("sub")) or "-2.05%" in str(row.get("sub"))
               for row in boards["explain_debate"].scenes[2].rows)
    assert any("8건 전부" == row.get("value") for row in boards["explain_open"].scenes[2].rows)


def test_every_renderer_a_story_names_has_a_composer_behind_it():
    """A story whose cut does not exist falls through to the record cut and lies."""

    import inspect

    from cli import main as cli
    from tradingagents.shorts.bank import STORIES
    from tradingagents.shorts.stories import STORIES as BUILDERS

    named = {story.renderer for story in STORIES if story.renderer}
    assert named <= set(BUILDERS)

    source = inspect.getsource(cli._shorts_build)
    # every renderer except the record cut has to be in the dispatch by name,
    # or it silently draws compose_record
    for renderer in sorted(named - {"record", "picks"}):
        assert f'"{renderer}": compose_{renderer}' in source, renderer


def test_a_month_of_choices_uses_the_whole_shelf():
    """The complaint that started this: every day was the same video."""

    from datetime import timedelta

    from tradingagents.shorts.bank import KST

    start = datetime(2026, 9, 17, 8, 40, tzinfo=KST)
    days = [(start + timedelta(days=d)).date() for d in range(40)]

    def payload(day: int) -> dict:
        exits = []
        if day in (2, 6, 9, 15, 21, 27):
            exits = [{"ticker_name": f"정리{day}", "realized_return": -0.09 if day % 2 else -0.16,
                      "exit_reason": "stop_loss", "exit_date": days[day].isoformat(), "entry_date": "2026-09-10"}]
        return {
            "summary": {"initial_cash": 1.5e8, "total_return": -0.0173, "closed_count": 8 + day, "win_count": 2},
            "accounts": [
                {"key": "paper", "label": "AI 확인", "summary": {"total_return": -0.0147, "open_count": 7, "closed_count": 4}},
                {"key": "rules", "label": "규칙 전용", "summary": {"total_return": -0.0205, "open_count": 6, "closed_count": 4}},
            ],
            "positions": [{"ticker_name": f"보유{i}", "account": "paper", "entry_date": days[day].isoformat(),
                           "average_price": 10000, "target_price": 11500, "stop_price": 9200} for i in range(4)],
            "closed": exits + [{"ticker_name": f"과거{i}", "realized_return": -0.03, "exit_reason": "stop_loss",
                                "exit_date": "2026-09-01", "entry_date": "2026-08-25"} for i in range(8)],
            "funnel": {"universe": 349, "picks": [{"name": "티에스이", "sub": "비중 확대", "value": "0.62"}],
                       "stages": [{"label": "1차 선별", "from": 349, "to": 34},
                                  {"label": "예측 기준 미달", "from": 34, "to": 19},
                                  {"label": "AI 토론 탈락", "from": 19, "to": 7}]},
            "curve": {"points": [{"date": f"d{i}"} for i in range(11)]},
        }

    ledger: list[dict] = []
    chosen: list[str] = []
    for day in range(40):
        when = start + timedelta(days=day)
        if when.weekday() >= 5:
            continue
        decision = plan(payload(day), now=when, ledger=ledger)
        chosen.append(decision["story"])
        ledger.append({"story": decision["story"], "date": days[day].isoformat()})

    assert len(chosen) >= 25
    # no two days running are the same story
    assert all(a != b for a, b in zip(chosen, chosen[1:]))
    # and the month reaches for most of what is built, not one or two cuts
    renderers = {BY_KEY[key].renderer for key in chosen}
    assert len(renderers) >= 5, renderers
    assert len(set(chosen)) >= 7, sorted(set(chosen))
    # the loss-record cut is no longer the majority of the month
    record_days = len([key for key in chosen if BY_KEY[key].renderer == "record"])
    assert record_days < len(chosen) / 3, f"{record_days}/{len(chosen)}"


def test_a_funnel_bar_is_never_narrower_than_the_count_written_inside_it():
    """The live run drew 3종목 as "3종": the label is in the ground colour."""

    import json as _json
    import re

    from tradingagents.shorts import build
    from tradingagents.shorts.hyperframes import FUNNEL_BAR, compose_funnel

    payload = {"funnel": {
        "universe": 349, "picks": [{"name": "JB금융지주", "sub": "규칙 통과", "value": "3.09점"}],
        "stages": [{"label": "거래대금·밸류·변동성", "from": 349, "to": 20},
                   {"label": "점수 상위만 추림", "from": 20, "to": 3}],
    }}
    board = build("funnel", payload, now=MONDAY, story="funnel")
    html, _ = compose_funnel(payload, board)

    values = _json.loads(re.search(r"STAGES = (\[.*?\]);", html, re.S).group(1))
    for row in values:
        label = f"{int(row['to'])}종목"
        # padding, a digit-width each, and room for 종목 — measured the same way
        # the composer floors it, so the bar always contains its own text
        assert row["scale"] * FUNNEL_BAR >= 34 + len(str(int(row["to"]))) * 26 + 58, label


def test_the_funnel_caption_says_what_the_number_beside_a_name_actually_is():
    """A rules-only run shows a screener score, and calling it AI confidence is a lie."""

    from tradingagents.shorts import build

    stages = [{"label": "거래대금·밸류·변동성", "from": 349, "to": 20},
              {"label": "점수 상위만 추림", "from": 20, "to": 3}]
    rules_only = build("funnel", {"funnel": {
        "universe": 349, "stages": stages, "scored_by": "screener",
        "picks": [{"name": "JB금융지주", "sub": "규칙 통과", "value": "3.09점"}]}},
        now=MONDAY, story="funnel")
    with_ai = build("funnel", {"funnel": {
        "universe": 349, "stages": stages, "scored_by": "confidence",
        "picks": [{"name": "JB금융지주", "sub": "비중 확대", "value": "0.62"}]}},
        now=MONDAY, story="funnel")

    assert "선별 점수" in rules_only.scenes[2].note
    assert "AI 토론 없이 규칙만으로" in rules_only.scenes[2].note
    assert "확신도" not in rules_only.scenes[2].note
    assert "확신도" in with_ai.scenes[2].note

    # and the narration follows it, because that is the half people hear
    assert "선별 점수" in rules_only.scenes[2].narration
    assert "AI가 얼마나 확신했는지" in with_ai.scenes[2].narration


def test_the_failure_path_cannot_be_killed_by_a_character_it_cannot_print():
    """An em dash in the failure message took the whole 08:40 run down."""

    import inspect

    from cli import main as cli

    source = inspect.getsource(cli._make_console)
    assert 'encoding="utf-8"' in source and 'errors="replace"' in source
    assert "sys.stdout" in source and "sys.stderr" in source
    # and the console the commands print through is the one that was fixed
    assert "console = _make_console()" in inspect.getsource(cli).split("def _make_console")[0] \
        or "_make_console()" in inspect.getsource(cli)


def test_an_upload_with_no_id_still_burns_the_story():
    """It went live on the channel anyway; skipping the ledger publishes twice."""

    import inspect

    from cli import main as cli

    source = inspect.getsource(cli.shorts_daily_command)
    head, tail = source.split("video_id = _video_id_in(answer)", 1)
    failure, success = tail.split("[green]발행 완료", 1)
    # the no-id branch records the story and still exits non-zero
    assert "record_published(story.key, video_id=None" in failure
    assert "confirmed=False" in failure and "raise typer.Exit(code=1)" in failure
    assert "confirmed=True" in success or "confirmed=True" in failure.rsplit("Exit(code=1)", 1)[-1]


def test_the_funnel_prefers_todays_run_and_one_an_ai_weighed_in_on():
    from cli.main import _best_funnel

    today, yesterday = "2026-09-17", "2026-09-16"
    rules_today = {"as_of_date": today, "scored_by": "screener"}
    debate_today = {"as_of_date": today, "scored_by": "confidence"}
    debate_yesterday = {"as_of_date": yesterday, "scored_by": "confidence"}

    # a rules-only run arriving first used to win, and the cut then said
    # "AI 토론 없이 규칙만으로" on a day the debate had in fact run
    assert _best_funnel([rules_today, debate_today], today) is debate_today
    # and yesterday's run never beats today's, however complete it is
    assert _best_funnel([debate_yesterday, rules_today], today) is rules_today
    assert _best_funnel([], today) is None


def test_the_funnel_names_the_day_it_is_actually_showing():
    """It said "오늘 아침 349종목" about yesterday's 349."""

    from tradingagents.shorts import build

    stages = [{"label": "거래대금·밸류·변동성", "from": 349, "to": 20},
              {"label": "점수 상위만 추림", "from": 20, "to": 3}]
    today = MONDAY.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).date().isoformat()

    fresh = build("funnel", {"funnel": {"universe": 349, "stages": stages, "picks": [],
                                        "as_of_date": today}}, now=MONDAY, story="funnel")
    stale = build("funnel", {"funnel": {"universe": 349, "stages": stages, "picks": [],
                                        "as_of_date": "2026-09-11"}}, now=MONDAY, story="funnel")

    assert "오늘 아침" in fresh.scenes[0].caption
    assert "오늘 아침" not in stale.scenes[0].caption and "9월 11일" in stale.scenes[0].caption
    assert "오늘 아침" not in stale.scenes[0].narration


def _shortlist_run(names, universe=300, as_of="2026-09-10"):
    return {"run": {"as_of_date": as_of, "universe_size": universe,
                    "metadata": {"screener_candidates": [
                        {"code": code, "name": name, "rank": index + 1, "composite": 3.0 - index * 0.1}
                        for index, (code, name) in enumerate(names)]}}}


def test_every_shortlisted_name_is_measured_over_the_same_number_of_days():
    """KOSDAQ's index lags KOSPI's here, so those names came back a day short."""

    from cli.main import _rejected_in

    names = [(f"00{i:04}", f"종목{i}") for i in range(12)]
    kosdaq = {names[i][0] for i in (0, 1, 2)}          # these only have four closes

    calls = []

    def fetcher(code, as_of, horizon):
        calls.append((code, horizon))
        days = min(horizon, 4) if code in kosdaq else horizon
        return 0.02 * (int(code) + 1), 0.01 * (int(code) + 1), days

    found = _rejected_in(_shortlist_run(names), {names[0][0], names[5][0]}, fetcher)
    assert found is not None
    # the horizon actually measured, and every row is on it
    assert found["horizon_days"] == 4
    assert len(found["rows"]) == 12                     # nothing silently dropped
    # the nine that came back long were re-asked at the common horizon
    assert len([call for call in calls if call[1] == 4]) == 9
    assert found["bought_count"] == 2 and found["passed_count"] == 10


def test_a_shortlist_with_nothing_to_compare_does_not_become_a_video():
    from cli.main import _rejected_in

    names = [(f"00{i:04}", f"종목{i}") for i in range(12)]
    fetcher = lambda code, as_of, horizon: (0.01, 0.01, horizon)

    # one name on either side is an anecdote, and the cut puts two averages up
    assert _rejected_in(_shortlist_run(names), {names[0][0]}, fetcher) is None
    assert _rejected_in(_shortlist_run(names), {n[0] for n in names[:9]}, fetcher) is None
    # and a shortlist too short to be a shortlist
    assert _rejected_in(_shortlist_run(names[:4]), {names[0][0], names[1][0]}, fetcher) is None
    # a vendor that answers for nobody
    assert _rejected_in(_shortlist_run(names), {names[0][0], names[1][0]},
                        lambda *a: (None, None, None)) is None


def test_the_shortlist_cut_says_which_side_won_either_way():
    """It has to read the same when the picking worked and when it did not."""

    from tradingagents.shorts import build

    def board(bought_alpha, passed_alpha):
        rows = [{"rank": 1, "name": "가", "code": "1", "bought": True, "raw": 0.0, "alpha": bought_alpha},
                {"rank": 2, "name": "나", "code": "2", "bought": False, "raw": 0.0, "alpha": passed_alpha}]
        return build("rejected", {"rejected": {
            "as_of_date": "2026-09-10", "horizon_days": 5, "universe": 300, "rows": rows,
            "bought_alpha": bought_alpha, "passed_alpha": passed_alpha,
            "bought_count": 5, "passed_count": 15, "best": rows[1] if passed_alpha > bought_alpha else rows[0],
        }}, now=MONDAY, story="rejected")

    lost = board(-0.0246, 0.0246)
    won = board(0.0246, -0.0246)

    assert "넘긴 15종목이 나았습니다." in lost.scenes[0].lines[1]
    assert "고른 5종목이 나았습니다." in won.scenes[0].lines[1]
    assert lost.title != won.title
    assert "넘긴 15종목이 더 올랐습니다" in lost.title
    # and neither version pretends one week settles it
    for item in (lost, won):
        assert "한 번의 결과" in item.scenes[2].note
        assert item.scenes[1].rows and len(item.scenes) == 4


def test_the_shortlist_story_is_on_the_shelf_once_it_has_both_sides():
    payload = _payload(closed_before=4)
    rejected = {"rows": [{"alpha": 0.01}], "bought_count": 5, "passed_count": 15,
                "bought_alpha": -0.0246, "passed_alpha": 0.0246}
    keys = {item.story.key for item in evaluate({**payload, "rejected": rejected}, now=MONDAY, ledger=[])}
    assert "rejected" in keys
    assert BY_KEY["rejected"].renderer == "rejected"
    # nothing to compare, nothing on the shelf
    assert "rejected" not in {item.story.key for item in evaluate(payload, now=MONDAY, ledger=[])}


def test_the_video_id_is_found_wherever_n8n_put_it():
    """Three mornings reported nothing published while the video was live."""

    from cli.main import _video_id_in

    # the shape we always expected
    assert _video_id_in({"ok": True, "videoId": "63THZaQxMn0"}) == "63THZaQxMn0"
    # what the upload node actually hands back, nested
    assert _video_id_in({"videoId": "", "upload": {"id": {"videoId": "dQw4w9WgXcQ"}}}) == "dQw4w9WgXcQ"
    assert _video_id_in({"upload": {"id": "dQw4w9WgXcQ"}}) == "dQw4w9WgXcQ"
    assert _video_id_in({"upload": [{"snippet": {"resourceId": {"videoId": "dQw4w9WgXcQ"}}}]}) == "dQw4w9WgXcQ"

    # and nothing that is not an eleven-character id gets mistaken for one
    assert _video_id_in({"ok": True, "videoId": "", "story": "curve"}) == ""
    assert _video_id_in({"upload": {"id": "abc"}}) == ""
    assert _video_id_in({"upload": {"kind": "youtube#video", "etag": "x" * 40}}) == ""
    assert _video_id_in(None) == "" and _video_id_in("") == ""
    # a self-referencing structure cannot spin it forever
    assert _video_id_in({"a": {"b": {"c": {"d": {"e": {"f": {"videoId": "dQw4w9WgXcQ"}}}}}}}) == ""


def test_the_stop_loss_claim_is_read_off_stored_runs_and_names_the_index():
    """The figures lived in a constant, copied from a sweep that was never saved."""

    from tradingagents.shorts.topics import (
        BASELINE_LABEL, CHANGED_LABEL, backtest_caption, backtest_proof,
    )

    runs = {
        BASELINE_LABEL: {"total_return": 0.5033, "max_drawdown": -0.2887,
                         "sharpe_ratio": 0.620116, "hit_rate": 0.3915},
        CHANGED_LABEL: {"total_return": 1.2646, "max_drawdown": -0.2402,
                        "sharpe_ratio": 1.156081, "hit_rate": 0.4912,
                        "benchmark_return": 1.684, "start_date": "2023-09-19",
                        "end_date": "2026-09-18"},
    }
    rows = backtest_proof(runs)
    assert ("누적 수익률", "+50.3%", "+126.5%") in rows
    assert ("샤프 지수", "0.62", "1.16") in rows
    assert ("승률", "39.1%", "49.1%") in rows

    # and the index, which the first version of this cut never showed at all:
    # the change beat the old rules and still lost to simply holding KOSPI
    caption = backtest_caption(runs)
    assert "2023-09-19~2026-09-18" in caption
    assert "+168.4%" in caption and "지수에는 못 미칩니다" in caption

    # no run, no claim — the beat cannot be drawn from a constant any more
    assert backtest_proof({}) == ()
    assert backtest_proof({BASELINE_LABEL: runs[BASELINE_LABEL]}) == ()


def test_a_sweep_can_actually_be_persisted():
    """--sweep returned before the persist block, so rule changes left no record."""

    import inspect

    from cli import main as cli

    source = inspect.getsource(cli.backtest_command)
    sweep = source.split("if sweep:", 1)[1].split("result = run_rule_backtest", 1)[0]
    assert "repo.save_backtest_run(variant.as_dict()" in sweep
    assert 'label=f"{label}:{name}"' in sweep          # one label per variant, so a claim is traceable
    assert "benchmark=benchmark or None" in sweep      # or the index column comes back empty


def _sweep(*, ran_on="2026-09-18", benchmark=1.684, live_first=True):
    names = ["변동성 제외 + 손절 8%", "변동성 상위 20% 제외", "익절 늘림 5%/20%",
             "손절 넓힘 8%/10%", "현행 5%/10%"]
    returns = [1.2646, 1.1322, 0.9655, 0.8737, 0.5033]
    variants = [
        {"name": name, "total_return": value, "max_drawdown": -0.24,
         "sharpe_ratio": 1.0, "hit_rate": 0.45, "trade_count": 800,
         "live": (index == 0) if live_first else (index == 4)}
        for index, (name, value) in enumerate(zip(names, returns))
    ]
    return {"start_date": "2023-09-19", "end_date": "2026-09-18", "ran_on": ran_on,
            "universe": 180, "benchmark": benchmark, "variants": variants,
            "best": variants[0], "live": next(item for item in variants if item["live"])}


def test_the_rule_sweep_counts_how_many_beat_the_index_not_each_other():
    """Ranking our own settings against each other proves nothing on its own."""

    from tradingagents.shorts import build

    board = build("sweep", {"sweep": _sweep()}, now=MONDAY, story="rule_test")
    assert "지수를 넘은 건 0가지" in board.title
    assert board.scenes[0].lines == ("제일 나은 것도", "지수는 못 넘었습니다.")
    assert board.scenes[2].value == "0"

    # and when something does clear it, the same cut says that instead
    beaten = build("sweep", {"sweep": _sweep(benchmark=0.60)}, now=MONDAY, story="rule_test")
    assert beaten.scenes[2].value == "4"
    assert "4가지" in beaten.scenes[0].lines[1]


def test_the_sweep_cut_marks_the_rule_actually_in_force():
    from tradingagents.shorts import build

    winner = build("sweep", {"sweep": _sweep(live_first=True)}, now=MONDAY, story="rule_test")
    labels = [row["label"] for row in winner.scenes[2].rows]
    assert labels[0].startswith("지금 쓰는 설정 · 변동성 제외 + 손절 8%")
    # the rule in force came first, so repeating it as "the best" is two rows
    # of one number — the runner-up is what cannot be read off the first row
    assert labels[1].startswith("다음으로 나았던 설정 · 변동성 상위 20% 제외")
    assert winner.scenes[2].rows[1]["value"] == "+113.2%"

    behind = build("sweep", {"sweep": _sweep(live_first=False)}, now=MONDAY, story="rule_test")
    assert behind.scenes[2].rows[0]["value"] == "+50.3%"
    assert behind.scenes[2].rows[1]["label"].startswith("이번에 제일 나았던 설정")
    # and it does not promise to switch to whatever won this one window
    assert "바로 바꾸지는 않습니다" in behind.scenes[2].note


def test_a_stale_sweep_is_not_this_week_s_experiment():
    payload = _payload(closed_before=4)
    fresh = {item.story.key for item in evaluate({**payload, "sweep": _sweep(ran_on="2026-09-13")},
                                                now=MONDAY, ledger=[])}
    assert "rule_test" in fresh

    stale = {item.story.key for item in evaluate({**payload, "sweep": _sweep(ran_on="2026-05-01")},
                                                now=MONDAY, ledger=[])}
    assert "rule_test" not in stale
    assert BY_KEY["rule_test"].renderer == "sweep"


def test_the_sweep_reader_marks_the_live_rule_from_the_stored_config():
    from cli.main import _sweep_in, _live_rule_key

    stop, volatility = _live_rule_key()
    rows = [
        {"label": "rules:변동성 제외 + 손절 8%", "start_date": "2023-09-19", "end_date": "2026-09-18",
         "universe_size": 180, "total_return": 1.2646, "benchmark_return": 1.684,
         "max_drawdown": -0.2402, "sharpe_ratio": 1.156, "hit_rate": 0.4912, "trade_count": 737,
         "created_at": "2026-09-18", "config": {"stop_loss_pct": stop, "volatility_exclude_top_pct": volatility}},
    ] + [
        {"label": f"rules:다른 설정{i}", "start_date": "2023-09-19", "end_date": "2026-09-18",
         "universe_size": 180, "total_return": 0.5 - i * 0.1, "benchmark_return": 1.684,
         "max_drawdown": -0.3, "sharpe_ratio": 0.5, "hit_rate": 0.39, "trade_count": 900,
         "created_at": "2026-09-18", "config": {"stop_loss_pct": 0.05, "volatility_exclude_top_pct": 0.0}}
        for i in range(4)
    ]
    found = _sweep_in(rows)
    assert found["variants"][0]["name"] == "변동성 제외 + 손절 8%"   # ranked, label prefix stripped
    assert found["variants"][0]["live"] is True
    assert [item["live"] for item in found["variants"][1:]] == [False] * 4
    assert found["live"]["name"] == found["best"]["name"]

    # too few variants is a single replay, not a comparison
    assert _sweep_in(rows[:3]) is None


def test_the_stop_loss_caption_admits_the_setting_was_picked_on_its_own_window():
    """It came first where it was chosen and last on the year it never saw."""

    from tradingagents.shorts.topics import BASELINE_LABEL, CHANGED_LABEL, backtest_caption

    runs = {
        BASELINE_LABEL: {"total_return": 0.5033},
        CHANGED_LABEL: {"total_return": 1.2646, "benchmark_return": 1.684,
                        "start_date": "2023-09-19", "end_date": "2026-09-18"},
        "walkforward": {"count": 7, "place": 7, "return": 0.2643, "benchmark": 0.9812},
    }
    caption = backtest_caption(runs)
    assert "7가지 중 꼴찌였습니다" in caption and "+26.4%" in caption
    assert "고른 구간에서 1위였을 뿐" in caption

    # a middling out-of-sample place is stated as a place, not as last
    runs["walkforward"] = {"count": 7, "place": 3, "return": 0.49}
    assert "7가지 중 3위였습니다" in backtest_caption(runs)

    # and with no walk-forward run the caption simply does not claim one
    runs.pop("walkforward")
    assert "남겨둔" not in backtest_caption(runs)


def test_the_cut_shows_the_stop_the_account_is_actually_trading_on():
    """It imported a module that does not exist and showed the fallback."""

    from tradingagents.harness.pipeline import PipelineConfig
    from tradingagents.shorts.topics import BY_TOPIC, stop_loss_pct

    live = float(PipelineConfig().stop_loss_pct)
    assert stop_loss_pct() == live
    # and the hero on screen is that number, not one typed into the topic
    assert BY_TOPIC["explain_stop"].hero == f"{live * 100:.0f}"
