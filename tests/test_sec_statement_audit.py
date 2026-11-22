from zipfile import ZipFile

import pandas as pd

from TrainingData.pit.sec_statement_audit import statement_evidence


def test_sec_extract_filters_segmentation_and_confirmation(tmp_path):
    archive = tmp_path / "quarter.zip"
    with ZipFile(archive, "w") as files:
        files.writestr("sub.txt", "adsh\tcik\tform\tperiod\tfy\tfp\taccepted\n"
                       "a\t1\t10-Q\t20220630\t2022\tQ2\t2022-07-26 16:32:00.0\n"
                       "b\t1\t10-K\t20241231\t2024\tFY\t2025-02-06 10:00:00.0\n")
        files.writestr("num.txt", "adsh\ttag\tversion\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\n"
                       "a\tAssets\tus-gaap/2022\t20220630\t0\tUSD\t\t\t100\n"
                       "a\tAssets\tus-gaap/2022\t20220630\t0\tUSD\tSegment\t\t25\n"
                       "b\tAssets\tus-gaap/2024\t20241231\t0\tUSD\t\t\t200\n")
        files.writestr("pre.txt", "adsh\ttag\tversion\tstmt\tplabel\n"
                       "a\tAssets\tus-gaap/2022\tBS\tTotal assets\n")
    subs, facts, labels = statement_evidence(archive, {"a", "b"})
    assert subs.adsh.tolist() == ["a"]
    assert subs.accepted_et.iloc[0].tz_convert("UTC") == pd.Timestamp("2022-07-26T20:32:00Z")
    assert facts.value.tolist() == ["100"]
    assert labels.plabel.tolist() == ["Total assets"]
