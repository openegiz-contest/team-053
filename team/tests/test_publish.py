"""Tests for the simulator service (team/sekis/sim_service.py), spec 2.1, 5.1, 5.2, work package D3.

The service loop runs against a fake publisher, a fake scenario source and a fake clock, so that
120 simulated seconds of the loop take a moment and need neither a broker nor Ditto: message rate
and budget, the Ditto-protocol envelopes against registry.json, the things that are never
published, scenario revisions (new, invalid, reset), the health file, publisher and Ditto
failures, the pace of the real-time loop, the log lines, and the process in fixture mode.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
if str(TEAM) not in sys.path:
    sys.path.insert(0, str(TEAM))

from sekis import sim_service  # noqa: E402
from sekis.advisor.service import SourceError  # noqa: E402
from sekis.sim import PublishPlanner, Simulator, STRING_FEATURES, load_registry  # noqa: E402

REGISTRY = load_registry()
CYRILLIC = re.compile("[А-Яа-яЁё]")
LOOP_S = 0.5
BASELINE = {"revision": 0.0, "label": "Базовый режим"}


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakePublisher:
    enabled = True

    def __init__(self, clock):
        self.clock = clock
        self.messages = []          # (real time, topic, payload)
        self.mode = "ok"            # "ok" | "refuse" (returns False) | "raise"
        self.attempts = 0
        self.closed = False

    def publish(self, topic, payload):
        self.attempts += 1
        if self.mode == "refuse":
            return False
        if self.mode == "raise":
            raise ConnectionError("broker went away")
        self.messages.append((self.clock.now, topic, payload))
        return True

    def close(self):
        self.closed = True


class FakeScenario:
    """The scenario thing as the service reads it: ``{feature id: value}`` or an error."""

    mode = "test"

    def __init__(self, **features):
        self.features = dict(BASELINE, **features)
        self.error = None
        self.reads = 0

    def write(self, **features):
        self.features = dict(self.features, **features)

    def read(self):
        self.reads += 1
        if self.error:
            raise self.error
        return dict(self.features)


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.publisher = FakePublisher(self.clock)
        self.scenario = FakeScenario()
        self.log = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.alive = os.path.join(self.tmp.name, "alive")
        self.sim = Simulator.from_files(seed=53)
        self.planner = PublishPlanner(self.sim, 1.0)
        self.service = sim_service.SimService(self.sim, self.planner, self.scenario, self.publisher,
                                              alive_file=self.alive, clock=self.clock, log=self.log.append)

    def run_loop(self, seconds):
        """Run the service pass by pass over ``seconds`` of fake real time."""
        for _ in range(round(seconds / LOOP_S)):
            self.service.tick()
            self.clock.now += LOOP_S

    def times(self):
        return [t for t, _, _ in self.publisher.messages]

    def names(self):
        return [topic.rsplit("/", 1)[-1] for _, topic, _ in self.publisher.messages]


def max_in_any_second(times):
    """Largest number of messages inside a half-open window of one second."""
    times = sorted(times)
    best, low = 0, 0
    for high, t in enumerate(times):
        while times[low] <= t - 1.0:
            low += 1
        best = max(best, high - low + 1)
    return best


class TestMessageRate(ServiceCase):
    def test_rate_never_exceeds_the_budget_and_averages_near_the_plan(self):
        self.run_loop(120)
        times = self.times()
        self.assertTrue(times)
        self.assertLessEqual(max_in_any_second(times), 20)
        # the plan: every thing once per period of its tier
        periods = self.planner.periods()
        planned = sum(1 / periods[self.sim.tier(name)] for name in self.planner._names)
        average = len(times) / 120
        self.assertAlmostEqual(average, planned, delta=0.15 * planned)
        self.assertLessEqual(average, 20)

    def test_every_published_thing_is_in_the_plan_and_gets_published(self):
        self.run_loop(120)
        self.assertEqual(set(self.names()), set(self.planner._names))
        self.assertEqual(len(self.planner._names), 94)

    def test_scale_slows_the_publishing(self):
        planner = PublishPlanner(self.sim, 2.0)
        service = sim_service.SimService(self.sim, planner, self.scenario, self.publisher, clock=self.clock,
                                         log=self.log.append)
        for _ in range(240):
            service.tick()
            self.clock.now += LOOP_S
        self.assertAlmostEqual(len(self.publisher.messages) / 120, 12.4 / 2, delta=1.5)

    def test_budget_holds_when_a_backlog_is_released(self):
        self.publisher.mode = "refuse"
        self.run_loop(30)
        self.assertEqual(self.publisher.messages, [])
        self.publisher.mode = "ok"
        self.run_loop(30)
        self.assertLessEqual(max_in_any_second(self.times()), 20)


class TestEnvelopes(ServiceCase):
    def test_payloads_are_valid_ditto_modify_messages_of_registry_things(self):
        self.run_loop(120)
        self.assertTrue(self.publisher.messages)
        things = {t["thingId"]: t for t in REGISTRY["things"]}
        for _, topic, payload in self.publisher.messages:
            self.assertTrue(topic.startswith("telemetry/sekis/"), topic)
            name = topic[len("telemetry/sekis/"):]
            thing = things[f"kz.sekis:{name}"]
            message = json.loads(payload)
            self.assertEqual(set(message), {"topic", "path", "value"})
            self.assertEqual(message["topic"], f"kz.sekis/{name}/things/twin/commands/modify")
            self.assertEqual(message["path"], "/features")
            registry_features = thing["features"]
            self.assertEqual(set(message["value"]), set(registry_features), name)
            for fid, body in message["value"].items():
                self.assertEqual(set(body), {"properties"}, (name, fid))
                self.assertEqual(set(body["properties"]), {"value"}, (name, fid))
                value = body["properties"]["value"]
                expected = registry_features[fid]["properties"]["value"]
                if isinstance(expected, str):
                    self.assertIsInstance(value, str, (name, fid))
                    self.assertIn(fid, STRING_FEATURES)
                else:
                    self.assertIsInstance(value, (int, float), (name, fid))
                    self.assertNotIsInstance(value, bool, (name, fid))
                    self.assertNotIn(fid, STRING_FEATURES)
                    self.assertFalse(value != value or abs(value) == float("inf"), (name, fid))

    def test_payload_carries_the_current_state(self):
        self.run_loop(60)
        last = {}
        for _, topic, payload in self.publisher.messages:
            last[topic] = json.loads(payload)
        shift = last["telemetry/sekis/enterprise"]["value"]["sim_time"]["properties"]["value"]
        self.assertEqual(shift[:10], "2027-01-01")
        self.assertGreater(self.sim.sim_days, 0)

    def test_scenario_and_advisor_things_are_never_published(self):
        self.run_loop(120)
        self.scenario.write(revision=1.0, fan_vs2_off=1.0)
        self.run_loop(60)
        names = set(self.names())
        self.assertNotIn("scenario", names)
        self.assertNotIn("advisor", names)
        self.assertNotIn("telemetry/sekis/scenario", [topic for _, topic, _ in self.publisher.messages])


class TestScenario(ServiceCase):
    def test_baseline_revision_is_applied_once_at_the_start(self):
        self.run_loop(5)
        starts = [line for line in self.log if "ревизия 0" in line]
        self.assertEqual(len(starts), 1)
        self.assertIn("применён", starts[0])
        self.assertRegex(starts[0], CYRILLIC)

    def test_new_revision_is_applied_within_two_seconds(self):
        self.run_loop(10)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 0.0)
        before = self.clock.now
        self.scenario.write(revision=1.0, label="Отказ вентилятора", fan_vs2_off=1.0)
        applied_at = None
        for _ in range(8):
            self.service.tick()
            if self.sim.knobs["fan_vs2_off"] == 1.0 and applied_at is None:
                applied_at = self.clock.now
            self.clock.now += LOOP_S
        self.assertIsNotNone(applied_at)
        self.assertLessEqual(applied_at - before, 2.0)
        lines = [line for line in self.log if "ревизия 1 " in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("fan_vs2_off", lines[0])
        self.assertIn("Отказ вентилятора", lines[0])

    def test_ditto_shape_is_accepted(self):
        self.scenario.write(revision=1.0, fan_vs2_off={"properties": {"value": 1.0}})
        self.run_loop(2)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 1.0)

    def test_invalid_revision_is_rejected_and_the_loop_goes_on(self):
        self.scenario.write(revision=1.0, fan_vs2_off=1.0)
        self.run_loop(5)
        day = self.sim.sim_days
        sent = len(self.publisher.messages)
        self.scenario.write(revision=2.0, label="Оба съезда закрыты", tu1_closed=1.0, tu2_closed=1.0)
        self.run_loop(10)
        self.assertEqual(self.sim.knobs["tu1_closed"], 0.0)
        self.assertEqual(self.sim.knobs["tu2_closed"], 0.0)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 1.0)        # the previous scenario stays
        rejected = [line for line in self.log if "ревизия 2 " in line]
        self.assertEqual(len(rejected), 1)                            # logged once, not every second
        self.assertIn("отклонён", rejected[0])
        self.assertRegex(rejected[0], CYRILLIC)
        self.assertGreater(self.sim.sim_days, day)                    # the simulation did not stop
        self.assertGreater(len(self.publisher.messages), sent)        # nor the publishing
        self.scenario.write(revision=3.0, label="Съезд ТУ2 закрыт", tu1_closed=0.0, tu2_closed=1.0)
        self.run_loop(3)
        self.assertEqual(self.sim.knobs["tu2_closed"], 1.0)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 1.0)

    def test_lower_revision_after_a_reset_is_applied(self):
        self.scenario.write(revision=7.0, fan_vs2_off=1.0)
        self.run_loop(3)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 1.0)
        self.scenario.write(revision=2.0, label="Базовый режим", fan_vs2_off=0.0)       # the Stand reset it
        self.run_loop(3)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 0.0)
        reset = [line for line in self.log if "ревизия 2 " in line]
        self.assertEqual(len(reset), 1)
        self.assertIn("сброс", reset[0])

    def test_revision_bump_alone_applies_and_logs_without_changes(self):
        self.run_loop(3)
        self.scenario.write(revision=1.0)
        self.run_loop(3)
        line = [line for line in self.log if "ревизия 1 " in line]
        self.assertEqual(len(line), 1)
        self.assertIn("параметры не изменились", line[0])

    def test_unchanged_scenario_is_not_applied_again(self):
        self.run_loop(20)
        self.assertEqual(len([line for line in self.log if "сценарий применён" in line]), 1)

    def test_scenario_read_failure_keeps_the_simulation_going(self):
        self.scenario.write(revision=1.0, fan_vs2_off=1.0)
        self.run_loop(3)
        self.scenario.error = SourceError("Ditto: нет ответа")
        sent = len(self.publisher.messages)
        day = self.sim.sim_days
        self.run_loop(20)
        self.assertGreater(self.sim.sim_days, day)
        self.assertGreater(len(self.publisher.messages), sent)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 1.0)
        failures = [line for line in self.log if "сценарий не прочитан" in line]
        self.assertEqual(len(failures), 1)
        self.assertRegex(failures[0], CYRILLIC)
        self.scenario.error = None
        self.scenario.write(revision=2.0, fan_vs2_off=0.0)
        self.run_loop(3)
        self.assertEqual(self.sim.knobs["fan_vs2_off"], 0.0)
        self.assertTrue(any("чтение сценария восстановлено" in line for line in self.log))

    def test_unexpected_exception_from_the_source_does_not_escape(self):
        self.scenario.error = RuntimeError("boom")
        self.run_loop(3)
        self.assertTrue(any("RuntimeError" in line for line in self.log))

    def test_missing_scenario_is_not_an_error(self):
        self.scenario.read = lambda: None
        self.run_loop(3)
        self.assertEqual(self.log, [])


class TestBackgroundSource(unittest.TestCase):
    class Inner:
        mode = "test"

        def __init__(self):
            self.calls = 0
            self.fail_until = 0

        def read(self):
            self.calls += 1
            if self.calls <= self.fail_until:
                raise SourceError("Ditto: нет ответа")
            return {"revision": 3.0}

    def wait_for(self, condition, seconds=5.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.01)
        return False

    def test_read_does_not_block_and_returns_the_last_value(self):
        inner = self.Inner()
        source = sim_service.BackgroundSource(inner, interval=0.01).start()
        try:
            self.assertTrue(self.wait_for(lambda: source.read() is not None))
            self.assertEqual(source.read(), {"revision": 3.0})
        finally:
            source.close()

    def test_failures_are_retried_with_growing_pauses_until_it_recovers(self):
        inner = self.Inner()
        inner.fail_until = 4
        source = sim_service.BackgroundSource(inner, interval=0.01, backoff_max=0.05).start()
        try:
            self.assertTrue(self.wait_for(lambda: source.failures >= 1))
            with self.assertRaises(SourceError):
                while True:
                    source.read()
                    time.sleep(0.001)
            self.assertTrue(self.wait_for(lambda: inner.calls > 4))
            self.assertTrue(self.wait_for(lambda: source.failures == 0))
            self.assertEqual(source.read(), {"revision": 3.0})
        finally:
            source.close()

    def test_unexpected_errors_are_retried_too(self):
        class Broken:
            calls = 0

            def read(self):
                Broken.calls += 1
                raise ValueError("bad document")

        source = sim_service.BackgroundSource(Broken(), interval=0.01, backoff_max=0.02).start()
        try:
            self.assertTrue(self.wait_for(lambda: Broken.calls >= 3))
            with self.assertRaises(SourceError):
                source.read()
        finally:
            source.close()

    def test_scenario_reader_picks_the_scenario_thing(self):
        class Things:
            def read(self):
                return {"scenario": {"revision": 4.0}, "other": {}}

        self.assertEqual(sim_service.ScenarioReader(Things()).read(), {"revision": 4.0})

        class Empty:
            def read(self):
                return {}

        self.assertIsNone(sim_service.ScenarioReader(Empty()).read())


class TestHealthFile(ServiceCase):
    def test_alive_file_is_created_and_refreshed(self):
        self.assertFalse(os.path.exists(self.alive))
        self.service.tick()
        self.assertTrue(os.path.exists(self.alive))
        os.utime(self.alive, (1.0, 1.0))
        self.service.tick()
        self.assertGreater(os.path.getmtime(self.alive), time.time() - 30)

    def test_alive_file_is_touched_on_every_pass(self):
        stamps = []
        original = self.service.touch_alive

        def counting():
            stamps.append(self.clock.now)
            original()

        self.service.touch_alive = counting
        self.run_loop(30)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertLessEqual(max(gaps), 10.0)

    def test_unwritable_alive_file_does_not_stop_the_loop(self):
        self.service.alive_file = os.path.join(self.tmp.name, "no-such-folder", "alive")
        self.run_loop(3)
        self.assertEqual(len([line for line in self.log if "файл готовности" in line]), 1)
        self.assertTrue(self.publisher.messages)


class TestPublisherFailures(ServiceCase):
    def test_refusing_broker_is_retried_without_losing_the_loop(self):
        self.run_loop(10)
        got = len(self.publisher.messages)
        self.publisher.mode = "refuse"
        day = self.sim.sim_days
        self.run_loop(20)
        self.assertEqual(len(self.publisher.messages), got)
        self.assertGreater(self.sim.sim_days, day)
        self.assertGreater(self.publisher.attempts, got)              # it keeps trying
        down = [line for line in self.log if "MQTT: сообщения не уходят" in line]
        self.assertEqual(len(down), 1)
        self.assertRegex(down[0], CYRILLIC)
        self.publisher.mode = "ok"
        self.run_loop(30)
        self.assertGreater(len(self.publisher.messages), got)
        self.assertTrue(any("отправка восстановлена" in line for line in self.log))
        self.assertEqual(self.service._pending.keys() - set(self.names()), set())

    def test_raising_publisher_is_survived(self):
        self.run_loop(5)
        self.publisher.mode = "raise"
        day = self.sim.sim_days
        self.run_loop(10)
        self.assertGreater(self.sim.sim_days, day)
        self.assertTrue(any("ошибка отправки" in line and "ConnectionError" in line for line in self.log))
        got = len(self.publisher.messages)
        self.publisher.mode = "ok"
        self.run_loop(10)
        self.assertGreater(len(self.publisher.messages), got)

    def test_a_failed_message_is_sent_again_with_the_newest_state(self):
        self.publisher.mode = "refuse"
        self.run_loop(1)
        waiting = list(self.service._pending)
        self.assertTrue(waiting)
        self.publisher.mode = "ok"
        self.run_loop(10)
        for name in waiting:
            self.assertIn(name, self.names())

    def test_pending_queue_stays_bounded(self):
        self.publisher.mode = "refuse"
        self.run_loop(120)
        self.assertLessEqual(len(self.service._pending), len(self.planner._names))

    def test_unserialisable_twin_is_skipped_not_fatal(self):
        original = self.sim.features
        broken = self.planner._names[0]

        def features(name):
            result = dict(original(name))
            if name == broken:
                result["x"] = float("nan")
            return result

        self.sim.features = features
        self.run_loop(30)
        self.assertNotIn(broken, self.names())
        self.assertTrue(any(broken in line for line in self.log))
        self.assertGreater(len(self.publisher.messages), 50)


class TestDailySummary(ServiceCase):
    def test_one_summary_line_per_simulated_day(self):
        self.sim.speedup = 2880.0          # a day in 60 passes
        self.run_loop(60 * 3 * LOOP_S + 1)
        days = [line for line in self.log if line.startswith("сутки")]
        self.assertEqual(len(days), 3, self.log)
        for index, line in enumerate(days, start=1):
            self.assertTrue(line.startswith(f"сутки {index}:"), line)
            for word in ("поднято руды", "переработано", "золота", "потребность", "подача", "узкое звено"):
                self.assertIn(word, line)
        self.assertIn("откатка", days[0])

    def test_no_summary_before_a_day_has_passed(self):
        self.run_loop(60)
        self.assertEqual([line for line in self.log if line.startswith("сутки")], [])


class FakeStop:
    """A stop event on the fake clock: ``wait`` advances the clock instead of sleeping."""

    def __init__(self, clock, until):
        self.clock = clock
        self.until = until
        self.waits = []

    def is_set(self):
        return self.clock.now >= self.until

    def wait(self, timeout):
        self.waits.append(timeout)
        self.clock.now += timeout
        return self.is_set()


class TestPace(ServiceCase):
    def run_with_cost(self, cost, seconds):
        start = self.clock.now
        stop = FakeStop(self.clock, start + seconds)
        original = self.service.tick

        def tick():
            original()
            self.clock.now += cost       # time the pass itself took

        self.service.tick = tick
        self.service.run(stop)
        return stop

    def test_fast_passes_keep_real_time_pace_without_drift(self):
        stop = self.run_with_cost(0.05, 100)
        # one pass per 0.5 s of real time: no accumulated error after 100 s
        self.assertAlmostEqual(self.service.ticks, 200, delta=1)
        self.assertAlmostEqual(self.sim.sim_days * 1440 * 60, 100 * 60, delta=60)
        self.assertTrue(stop.waits)

    def test_slow_passes_skip_the_sleep(self):
        stop = self.run_with_cost(0.7, 14)
        self.assertEqual(stop.waits, [])
        self.assertEqual(self.service.ticks, 20)

    def test_lag_is_given_up_after_a_few_seconds(self):
        original = self.service.tick
        passes = []

        def tick():
            original()
            passes.append(self.clock.now)
            self.clock.now += 20.0 if len(passes) == 3 else 0.05      # one very long stall

        self.service.tick = tick
        stop = FakeStop(self.clock, self.clock.now + 60)
        self.service.run(stop)
        after = [b - a for a, b in zip(passes, passes[1:])]
        # after the stall the loop does not run the owed 40 passes back to back
        self.assertGreater(len([gap for gap in after[3:] if gap >= 0.4]), len(after[3:]) - 3)

    def test_defect_in_a_pass_is_logged_and_the_loop_goes_on(self):
        calls = []

        def broken():
            calls.append(1)
            self.clock.now += 0.0
            if len(calls) < 5:
                raise RuntimeError("defect")

        self.service.tick = broken
        stop = FakeStop(self.clock, self.clock.now + 10)
        self.service.run(stop)
        self.assertGreater(len(calls), 5)
        self.assertEqual(len([line for line in self.log if "сбой цикла" in line]), 1)

    def test_run_touches_the_health_file_while_waiting(self):
        stop = FakeStop(self.clock, self.clock.now + 5)
        self.service.run(stop)
        self.assertTrue(os.path.exists(self.alive))

    def test_stop_event_ends_the_loop_cleanly(self):
        stop = threading.Event()
        worker = threading.Thread(target=self.service.run, args=(stop,))
        clock = self.service.clock = time.monotonic
        worker.start()
        time.sleep(1.3)
        stop.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertGreaterEqual(self.service.ticks, 2)


class TestConfiguration(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ("SIM_SEED", "SIM_SPEEDUP", "PUBLISH_SCALE")}
        self.addCleanup(self.restore)
        self.log = []

    def restore(self):
        for key, value in self.saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value

    def test_defaults_come_from_the_parameter_file(self):
        service, _ = sim_service.build_service("1", None, self.log.append)
        self.assertEqual((service.sim.seed, service.sim.speedup, service.planner.scale), (53, 60.0, 1.0))
        self.assertEqual(self.log, [])

    def test_environment_sets_seed_speedup_and_scale(self):
        os.environ.update(SIM_SEED="7", SIM_SPEEDUP="120", PUBLISH_SCALE="2.5")
        service, _ = sim_service.build_service("1", None, self.log.append)
        self.assertEqual((service.sim.seed, service.sim.speedup, service.planner.scale), (7, 120.0, 2.5))
        self.assertEqual(service.planner.periods()["L"], 20 * 2.5)

    def test_bad_values_fall_back_to_defaults_and_are_logged(self):
        os.environ.update(SIM_SEED="abc", SIM_SPEEDUP="-3", PUBLISH_SCALE="0")
        service, _ = sim_service.build_service("1", None, self.log.append)
        self.assertEqual((service.sim.seed, service.sim.speedup, service.planner.scale), (53, 60.0, 1.0))
        self.assertEqual(len(self.log), 3)
        for line in self.log:
            self.assertRegex(line, CYRILLIC)

    def test_fixture_mode_has_no_broker_and_no_ditto(self):
        service, (source, mqtt) = sim_service.build_service("1", None, self.log.append)
        self.assertFalse(service.publisher.enabled)
        self.assertIsInstance(service.publisher, sim_service.NullPublisher)
        self.assertIn("без брокера", mqtt)
        service.tick()
        self.assertGreater(service.publisher.count, 0)

    def test_fixture_file_supplies_the_scenario(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"things": {"kz.sekis:scenario": {"f": {"revision": 4, "label": "Файл",
                                                                   "fan_vs2_off": 1.0}}}}, handle)
            service, _ = sim_service.build_service(path, None, self.log.append)
            service.tick()
            self.assertEqual(service.sim.knobs["fan_vs2_off"], 1.0)
            self.assertTrue(any("ревизия 4 «Файл»" in line for line in self.log))

    def test_start_line_names_seed_speedup_and_periods(self):
        service, (source, mqtt) = sim_service.build_service("1", None, self.log.append)
        line = service.start_line(source, mqtt)
        self.assertRegex(line, CYRILLIC)
        for text in ("зерно 53", "×60", "2/6/20 с", "18 сообщений/с"):
            self.assertIn(text, line)


class TestProcess(unittest.TestCase):
    """``python -m sekis.sim_service`` in fixture mode: no Ditto, no broker."""

    def test_process_runs_logs_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            alive = os.path.join(folder, "alive")
            env = dict(os.environ, PYTHONIOENCODING="utf-8", SIM_FIXTURE="1", ALIVE_FILE=alive,
                       SIM_SPEEDUP="14400")
            for name in ("DITTO_URL", "DITTO_PASSWORD", "MQTT_HOST"):
                env.pop(name, None)
            result = subprocess.run([sys.executable, "-m", "sekis.sim_service", "--seconds", "8"], cwd=str(TEAM),
                                    env=env, capture_output=True, timeout=60)
            output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
            self.assertEqual(result.returncode, 0, output)
            self.assertNotIn("Traceback", output)
            lines = output.strip().splitlines()
            self.assertIn("имитатор запущен", lines[0])
            self.assertIn("зерно 53", lines[0])
            self.assertIn("имитатор остановлен", lines[-1])
            self.assertTrue(any("сутки 1:" in line for line in lines), output)
            self.assertTrue(os.path.exists(alive))
            self.assertLess(time.time() - os.path.getmtime(alive), 30)


class TestPackageSource(unittest.TestCase):
    def test_service_file_is_utf8_lf_and_uses_only_the_allowed_packages(self):
        import ast
        source = (TEAM / "sekis" / "sim_service.py").read_bytes()
        self.assertNotIn(b"\r\n", source)
        allowed = {"__future__", "argparse", "json", "os", "signal", "sys", "threading", "time", "collections",
                   "pathlib", "typing", "paho"}
        for node in ast.walk(ast.parse(source.decode("utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            for name in names:
                self.assertIn(name.split(".")[0], allowed, name)

    def test_compose_points_at_the_module(self):
        compose = (TEAM / "compose.yml").read_text(encoding="utf-8")
        self.assertIn('"sekis.sim_service"', compose)
        self.assertTrue((TEAM / "sekis" / "sim_service.py").exists())


if __name__ == "__main__":
    unittest.main()
