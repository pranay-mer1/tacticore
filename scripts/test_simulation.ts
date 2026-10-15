import {
  calculateSimulationStats,
  createSimulation,
  deriveSimulationInsights,
  filterSimulationEvents,
} from "../src/simulation.ts";

function assert(condition: unknown, message = "Assertion failed."): asserts condition {
  if (!condition) throw new Error(message);
}

function assertEquals(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`Expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}.`);
  }
}

Deno.test("simulation generation is repeatable and contains match metadata", () => {
  const first = createSimulation(20261015);
  const second = createSimulation(20261015);
  assertEquals(first, second);
  assertEquals(first.lineups[first.homeTeam].length, 11);
  assertEquals(first.lineups[first.awayTeam].length, 11);
  assert(first.events.some((event) => event.type === "pass"));
  assert(first.events.some((event) => event.type === "shot"));
  assert(first.events.some((event) => event.type === "tackle"));
  assert(first.events.some((event) => event.type === "pressure"));
  assert(first.events.some((event) => event.type === "possession"));
  assert(first.events.some((event) => event.type === "substitution"));
  assertEquals(first.events.every((event) => event.matchId === first.id), true);
});

Deno.test("statistics equal the currently received event log", () => {
  const match = createSimulation(20261015);
  const received = match.events.slice(0, 37);
  const stats = calculateSimulationStats(received, match.homeTeam);
  assertEquals(stats.passes, received.filter((event) => event.type === "pass").length);
  assertEquals(stats.completedPasses, received.filter((event) => event.type === "pass" && event.completed).length);
  assertEquals(stats.shots, received.filter((event) => event.type === "shot").length);
  assertEquals(stats.shotsOnTarget, received.filter((event) => event.type === "shot" && event.onTarget).length);
  assertEquals(stats.tackles, received.filter((event) => event.type === "tackle").length);
  assertEquals(
    stats.playerPerformance.reduce((total, player) => total + player.actions, 0),
    received.filter((event) => event.type !== "possession").length,
  );
});

Deno.test("a failed pass is not counted as a turnover until possession changes", () => {
  const match = createSimulation(20261015);
  const failedPass = match.events.find((event) =>
    event.type === "pass" && event.completed === false && event.team === match.homeTeam &&
    event.x <= 33 && event.matchTime >= 18 * 60,
  )!;
  const possessionChange = match.events.find((event) =>
    event.type === "possession" && event.fromPlayer === failedPass.player &&
    event.fromTeam === failedPass.team && event.matchTime >= failedPass.matchTime &&
    event.matchTime - failedPass.matchTime <= 45,
  )!;
  const passOnly = match.events.filter((event) => event.id === failedPass.id);
  const withPossession = match.events.filter((event) =>
    event.id === failedPass.id || event.id === possessionChange.id,
  );
  assertEquals(calculateSimulationStats(passOnly, match.homeTeam).turnovers, 0);
  assertEquals(calculateSimulationStats(withPossession, match.homeTeam).turnovers, 1);
});

Deno.test("insights and supporting evidence never include events beyond replay time", () => {
  const match = createSimulation(20261015);
  const ids = new Set(match.events.map((event) => event.id));
  let foundTurnoverPattern = false;
  let foundPressureShift = false;
  for (let count = 1; count <= match.events.length; count += 1) {
    const received = match.events.slice(0, count);
    const currentTime = received[received.length - 1].matchTime;
    const insights = deriveSimulationInsights(match, received, "analyst", "en", "all", "", "all", "");
    for (const insight of insights) {
      assert(insight.match_time <= currentTime);
      assert(insight.valid_until >= currentTime);
      foundTurnoverPattern ||= insight.headline === "Repeated defensive-third turnovers";
      foundPressureShift ||= insight.headline === "Pressure has shifted";
      for (const id of insight.supporting_event_ids) {
        assert(ids.has(id));
        assert(received.some((event) => event.id === id), `Insight referenced a future event: ${id}`);
      }
    }
  }
  assert(foundTurnoverPattern, "The demonstration seed should show a defensive-turnover finding.");
  assert(foundPressureShift, "The demonstration seed should show a pressure-window finding.");
});

Deno.test("filters include linked turnover evidence and narrow insight context", () => {
  const match = createSimulation(20261015);
  const homeTurnoverPlayer = match.events.find((event) =>
    event.type === "pass" && event.completed === false && event.team === match.homeTeam,
  )!.player;
  const received = match.events.filter((event) => event.matchTime <= 25 * 60);
  const filtered = filterSimulationEvents(received, match.homeTeam, "");
  const playerFiltered = filterSimulationEvents(received, "all", homeTurnoverPlayer);
  assert(playerFiltered.some((event) => event.type === "possession" && event.fromPlayer === homeTurnoverPlayer));
  const insights = deriveSimulationInsights(match, received, "analyst", "en", match.homeTeam, "", "all", "");
  assert(insights.some((insight) => insight.headline === "Repeated defensive-third turnovers"));
  const supportedIds = new Set(insights.flatMap((insight) => insight.supporting_event_ids));
  assert([...supportedIds].every((id) => filtered.some((event) => event.id === id)));
});
