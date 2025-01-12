#!/usr/bin/env python3
import time
import unittest
from collections import defaultdict

import cereal.messaging as messaging
from cereal.services import service_list
from selfdrive.manager.process_config import managed_processes
from system.hardware import TICI

TEST_TIMESPAN = 30
LAG_FRAME_TOLERANCE = 0.5 # ms

CAMERAS = ('roadCameraState', 'driverCameraState', 'wideRoadCameraState')


class TestCamerad(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    if not TICI:
      raise unittest.SkipTest

    # run camerad and record logs
    managed_processes['camerad'].start()
    time.sleep(3)
    socks = {c: messaging.sub_sock(c, conflate=False, timeout=100) for c in CAMERAS}

    cls.logs = defaultdict(list)
    start_time = time.monotonic()
    while time.monotonic()- start_time < TEST_TIMESPAN:
      for cam, s in socks.items():
        cls.logs[cam] += messaging.drain_sock(s)
      time.sleep(0.2)
    managed_processes['camerad'].stop()

    cls.log_by_frame_id = defaultdict(list)
    for cam, msgs in cls.logs.items():
      expected_frames = service_list[cam].frequency * TEST_TIMESPAN
      assert expected_frames*0.95 < len(msgs) < expected_frames*1.05, f"unexpected frame count {cam}: {expected_frames=}, got {len(msgs)}"

      for m in msgs:
        cls.log_by_frame_id[getattr(m, m.which()).frameId].append(m)

    # strip beginning and end
    for _ in range(3):
      mn, mx = min(cls.log_by_frame_id.keys()), max(cls.log_by_frame_id.keys())
      del cls.log_by_frame_id[mn]
      del cls.log_by_frame_id[mx]

  @classmethod
  def tearDownClass(cls):
    managed_processes['camerad'].stop()

  def test_frame_skips(self):
    skips = {}
    frame_ids = self.log_by_frame_id.keys()
    for frame_id in range(min(frame_ids), max(frame_ids)):
      seen_cams = [msg.which() for msg in self.log_by_frame_id[frame_id]]
      skip_cams = set(CAMERAS) - set(seen_cams)
      if len(skip_cams):
        skips[frame_id] = skip_cams
    assert len(skips) == 0, f"Found frame skips, missing cameras for the following frames: {skips}"

  def test_frame_sync(self):
    frame_times = {frame_id: [getattr(m, m.which()).timestampSof for m in msgs] for frame_id, msgs in self.log_by_frame_id.items()}
    diffs = {frame_id: (max(ts) - min(ts))/1e6 for frame_id, ts in frame_times.items()}


    def get_desc(fid, diff):
      cam_times = [(m.which(), getattr(m, m.which()).timestampSof/1e6) for m in self.log_by_frame_id[fid]]
      return f"{diff=} {cam_times=}"
    laggy_frames = {k: get_desc(k, v) for k, v in diffs.items() if v > LAG_FRAME_TOLERANCE}
    assert len(laggy_frames) == 0, f"Frames not synced properly: {laggy_frames=}"

if __name__ == "__main__":
  unittest.main()
