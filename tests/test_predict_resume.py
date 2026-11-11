"""A prediction that a start began and did not finish is run again at the next start.

The predicted pipelines are built after the programs are translated and hookshot_prepared.bin says so. A start closed (or ended)
during the prediction left the rest unbuilt for good: the next start found the programs prepared, skipped the prediction, and play
compiled those pipelines as they were first drawn. predict_run (gpu/vk/vk_draw.cpp) now keeps hookshot_pipelines.bin.predicting from
its start to its end (not removed when stopped), and every caller (the Builder's run, the start-up screen, the console start) runs
the prediction when the marker is there even if nothing was translated.

Source checks only. python -I -B tests/test_predict_resume.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def body(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: expected one %r" % marker)
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def main():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    main_cpp = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    run = body(draw, "void predict_run(void (*progress)(size_t done, size_t total)) {")
    made = run.index('fopen(predict_pending_path().c_str(), "wb")')
    if made > run.index("predict_pipelines("):
        raise SystemExit("FAIL: the marker is made after the prediction has begun deciding")
    if "if (!prepare_stopped()) remove(predict_pending_path().c_str());" not in run:
        raise SystemExit("FAIL: a stopped prediction's marker is removed (or a finished one's kept)")
    started = body(main_cpp, "bool started_up() {")
    screen = main_cpp[main_cpp.index("void prepare_with_screen() {"):main_cpp.index("bool started_up() {")]
    for where, text in (("the Builder's run and the console start", started), ("the start-up screen", screen)):
        if "predict_pending()" not in text:
            raise SystemExit("FAIL: %s does not finish an unfinished prediction" % where)
    if started.count("predict_pending()") < 2:
        raise SystemExit("FAIL: the Builder's run or the console start does not finish an unfinished prediction")
    print("PASS: an unfinished prediction is run again at the next start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
