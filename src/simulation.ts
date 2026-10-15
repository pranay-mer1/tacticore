export type SimulationEventType = "pass" | "shot" | "tackle" | "possession" | "pressure" | "substitution";
export type AudienceMode = "analyst" | "fan";
export type SimulationLanguage = "en" | "es";

export type SimulationEvent = {
  id: string;
  matchId: string;
  matchTime: number;
  team: string;
  player: string;
  type: SimulationEventType;
  x: number;
  y: number;
  completed?: boolean;
  onTarget?: boolean;
  outcome?: string;
  fromTeam?: string;
  fromPlayer?: string;
  substitutedPlayer?: string;
};

export type SimulationMatch = {
  id: string;
  seed: number;
  homeTeam: string;
  awayTeam: string;
  venue: string;
  competition: string;
  lineups: Record<string, string[]>;
  events: SimulationEvent[];
};

export type SimulationInsight = {
  id: string;
  match_id: string;
  match_time: number;
  valid_until: number;
  headline: string;
  explanation: string;
  supporting_event_ids: string[];
  audience_mode: AudienceMode;
  language: SimulationLanguage;
  observation: string;
  hypothesis: string;
  team: string;
  player: string;
};

export type SimulationStats = {
  passes: number;
  completedPasses: number;
  passAccuracy: number | null;
  shots: number;
  shotsOnTarget: number;
  tackles: number;
  turnovers: number;
  playerPerformance: Array<{ player: string; team: string; actions: number; passes: number; shots: number; tackles: number }>;
  attackingZones: { left: number; central: number; right: number };
};

const ROSTERS: Record<string, string[]> = {
  "Northbridge FC": ["M. Silva", "J. Okafor", "A. Reed", "L. Costa", "T. Nordin", "P. James", "E. Malik", "D. Chen", "R. Santos", "K. Byrne", "I. Petrov", "S. Yamada", "C. Mensah", "O. Diallo"],
  "Harbor Athletic": ["A. Novak", "F. Laurent", "M. Brooks", "S. Ibrahim", "D. Walsh", "R. Kim", "J. Moreau", "B. Olsen", "N. Ahmed", "V. Rossi", "H. Park", "G. Costa", "L. Martin", "E. Young"],
};

function randomFor(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function last<T>(items: T[]): T | undefined {
  return items[items.length - 1];
}

export function createSimulation(seed: number): SimulationMatch {
  const random = randomFor(seed);
  const homeTeam = "Northbridge FC";
  const awayTeam = "Harbor Athletic";
  const events: SimulationEvent[] = [];
  let possession = homeTeam;
  let elapsed = 0;
  let sequence = 0;
  const add = (
    type: SimulationEventType,
    matchTime: number,
    team: string,
    player: string,
    x: number,
    y: number,
    extra: Partial<SimulationEvent> = {},
  ) => {
    events.push({
      id: `sim-${seed}-${String(++sequence).padStart(4, "0")}`,
      matchId: `simulation-${seed}`,
      matchTime,
      team,
      player,
      type,
      x: clamp(Math.round(x), 4, 96),
      y: clamp(Math.round(y), 5, 95),
      ...extra,
    });
  };

  for (let index = 0; index < 136; index += 1) {
    elapsed += 28 + Math.floor(random() * 32);
    const minute = Math.min(90, Math.floor(elapsed / 60));
    if (minute >= 90) break;
    const roster = ROSTERS[possession];
    const player = roster[Math.floor(random() * 11)];
    const isHome = possession === homeTeam;
    const attackX = isHome ? 24 + random() * 68 : 76 - random() * 68;
    const y = 12 + random() * 76;
    const action = random();
    if (action < 0.61) {
      const completed = random() > 0.19;
      const x = 12 + random() * 76;
      add("pass", elapsed, possession, player, x, y, { completed });
      if (!completed) {
        const opponent = possession === homeTeam ? awayTeam : homeTeam;
        add("possession", elapsed + 8, opponent, ROSTERS[opponent][Math.floor(random() * 11)], x, y, { fromTeam: possession, fromPlayer: player });
        possession = opponent;
      }
    } else if (action < 0.72) {
      add("pressure", elapsed, possession === homeTeam ? awayTeam : homeTeam, ROSTERS[possession === homeTeam ? awayTeam : homeTeam][Math.floor(random() * 11)], attackX, y);
    } else if (action < 0.84) {
      add("tackle", elapsed, possession === homeTeam ? awayTeam : homeTeam, ROSTERS[possession === homeTeam ? awayTeam : homeTeam][Math.floor(random() * 11)], attackX, y, { completed: random() > 0.4 });
    } else if (action < 0.92) {
      const isGoal = random() > 0.92;
      const onTarget = isGoal || random() > 0.55;
      add("shot", elapsed, possession, player, isHome ? 84 + random() * 12 : 16 - random() * 12, y, {
        onTarget,
        outcome: isGoal ? "Goal" : onTarget ? "Saved" : "Off target",
      });
      if (random() > 0.82) {
        const opponent = possession === homeTeam ? awayTeam : homeTeam;
        add("possession", elapsed + 12, opponent, ROSTERS[opponent][Math.floor(random() * 11)], isHome ? 16 : 84, 50, { fromTeam: possession, fromPlayer: player });
        possession = opponent;
      }
    } else {
      const opponent = possession === homeTeam ? awayTeam : homeTeam;
      add("possession", elapsed, opponent, ROSTERS[opponent][Math.floor(random() * 11)], attackX, y, { fromTeam: possession, fromPlayer: player });
      possession = opponent;
    }
  }

  const forcedTurnoverTimes = [18 * 60, 21 * 60, 24 * 60];
  for (const [index, time] of forcedTurnoverTimes.entries()) {
    const player = ROSTERS[homeTeam][index + 1];
    const x = 20 + index * 5;
    add("pass", time, homeTeam, player, x, 26 + index * 18, { completed: false });
    add("possession", time + 7, awayTeam, ROSTERS[awayTeam][index + 2], x, 26 + index * 18, { fromTeam: homeTeam, fromPlayer: player });
  }

  for (const minute of [47, 50, 52, 55, 58, 62, 64, 66, 68, 70]) {
    const team = minute % 4 === 1 ? homeTeam : awayTeam;
    const roster = ROSTERS[team];
    add("pressure", minute * 60, team, roster[(minute + 3) % 11], team === homeTeam ? 35 + (minute % 15) : 65 - (minute % 15), 18 + (minute * 7) % 64);
  }

  const substitutionTimes = [61 * 60, 68 * 60, 74 * 60, 79 * 60];
  for (const [index, time] of substitutionTimes.entries()) {
    const team = index % 2 === 0 ? homeTeam : awayTeam;
    const roster = ROSTERS[team];
    add("substitution", time, team, roster[11 + (index % 3)], 50, 50, { substitutedPlayer: roster[index] });
  }

  events.sort((first, second) => first.matchTime - second.matchTime || first.id.localeCompare(second.id));
  const starters = (team: string) => [...ROSTERS[team].slice(0, 11)];
  return {
    id: `simulation-${seed}`,
    seed,
    homeTeam,
    awayTeam,
    venue: "Tacticore Synthetic Arena",
    competition: "Hackathon Simulation",
    lineups: { [homeTeam]: starters(homeTeam), [awayTeam]: starters(awayTeam) },
    events: events.map((event, index) => ({ ...event, id: `sim-${seed}-${String(index + 1).padStart(4, "0")}` })),
  };
}

export function calculateSimulationStats(events: SimulationEvent[], homeTeam: string): SimulationStats {
  const playerStats = new Map<string, SimulationStats["playerPerformance"][number]>();
  let passes = 0;
  let completedPasses = 0;
  let shots = 0;
  let shotsOnTarget = 0;
  let tackles = 0;
  let turnovers = 0;
  const attackingZones = { left: 0, central: 0, right: 0 };

  for (const event of events) {
    if (event.type === "possession") {
      if (event.fromTeam && event.fromPlayer) {
        const lostPass = events.some((candidate) =>
          candidate.type === "pass" &&
          candidate.completed === false &&
          candidate.team === event.fromTeam &&
          candidate.player === event.fromPlayer &&
          candidate.matchTime <= event.matchTime &&
          event.matchTime - candidate.matchTime <= 45 &&
          isDefensiveThird(candidate, homeTeam),
        );
        if (lostPass) turnovers += 1;
      }
      continue;
    }
    const current = playerStats.get(`${event.team}:${event.player}`) ?? {
      player: event.player,
      team: event.team,
      actions: 0,
      passes: 0,
      shots: 0,
      tackles: 0,
    };
    current.actions += 1;
    if (event.type === "pass") {
      passes += 1;
      current.passes += 1;
      if (event.completed) completedPasses += 1;
    } else if (event.type === "shot") {
      shots += 1;
      current.shots += 1;
      if (event.onTarget) shotsOnTarget += 1;
      const attackingX = event.team === homeTeam ? event.x : 100 - event.x;
      attackingZones[attackingX < 40 ? "left" : attackingX > 60 ? "right" : "central"] += 1;
    } else if (event.type === "tackle") {
      tackles += 1;
      current.tackles += 1;
    }
    playerStats.set(`${event.team}:${event.player}`, current);
  }

  return {
    passes,
    completedPasses,
    passAccuracy: passes ? Math.round((completedPasses / passes) * 100) : null,
    shots,
    shotsOnTarget,
    tackles,
    turnovers,
    playerPerformance: [...playerStats.values()].sort((first, second) => second.actions - first.actions),
    attackingZones,
  };
}

export function isDefensiveThird(event: SimulationEvent, homeTeam: string): boolean {
  const defendingX = event.team === homeTeam ? event.x : 100 - event.x;
  return defendingX <= 33;
}

function languageCopy(language: SimulationLanguage) {
  return language === "es"
    ? {
      turnover: "Pérdidas repetidas en zona defensiva",
      turnoverObservation: (team: string, count: number) => `${team} perdió la posesión en su tercio defensivo ${count} veces durante los últimos 10 minutos.`,
      turnoverHypothesis: "La presión rival podría estar cerrando las salidas cortas; revisa las secuencias antes de cambiar la estructura.",
      pressure: (team: string, delta: number) => `${team} registró ${delta} acciones de presión más en esta ventana de 10 minutos.`,
      pressureHypothesis: "El aumento podría indicar una presión más agresiva; confirma si el rival también cambió su salida.",
      defaultHeadline: "Secuencia de partido",
      defaultObservation: (count: number) => `${count} acciones observadas en esta ventana.`,
      defaultHypothesis: "Observa cómo evoluciona la siguiente secuencia antes de sacar conclusiones.",
      analystExplain: "Evidencia de partido observada",
      fanExplain: "Momento para seguir",
    }
    : {
      turnover: "Repeated defensive-third turnovers",
      turnoverObservation: (team: string, count: number) => `${team} lost possession in its defensive third ${count} times in the last 10 minutes.`,
      turnoverHypothesis: "The opponent's pressure may be closing short build-up options; review the sequences before changing shape.",
      pressure: (team: string, delta: number) => `${team} recorded ${delta} more pressure actions in this 10-minute window.`,
      pressureHypothesis: "The increase may indicate a more aggressive press; check whether the opponent also changed its build-up.",
      defaultHeadline: "Match sequence",
      defaultObservation: (count: number) => `${count} actions observed in this window.`,
      defaultHypothesis: "Watch the next sequence before drawing a conclusion.",
      analystExplain: "Observed match evidence",
      fanExplain: "Moment to watch",
    };
}

export function filterSimulationEvents(
  events: SimulationEvent[],
  teamFilter: string,
  playerFilter: string,
): SimulationEvent[] {
  const playerQuery = playerFilter.toLowerCase();
  return events.filter((event) => {
    const relatedPossession = event.type === "possession";
    const teamMatches = teamFilter === "all" || event.team === teamFilter ||
      (relatedPossession && event.fromTeam === teamFilter);
    const playerMatches = !playerQuery || event.player.toLowerCase().includes(playerQuery) ||
      (relatedPossession && event.fromPlayer?.toLowerCase().includes(playerQuery));
    return teamMatches && playerMatches;
  });
}

export function deriveSimulationInsights(
  match: SimulationMatch,
  receivedEvents: SimulationEvent[],
  audience: AudienceMode,
  language: SimulationLanguage,
  teamFilter: string,
  playerFilter: string,
  favoriteTeam: string,
  followedPlayer: string,
): SimulationInsight[] {
  const copy = languageCopy(language);
  const currentTime = last(receivedEvents)?.matchTime ?? 0;
  const filtered = filterSimulationEvents(receivedEvents, teamFilter, playerFilter);
  const recent = filtered.filter((event) => event.matchTime >= currentTime - 600);
  const prior = filtered.filter((event) => event.matchTime >= currentTime - 1200 && event.matchTime < currentTime - 600);
  const turnoversByTeam = new Map<string, SimulationEvent[]>();
  for (let index = 0; index < recent.length; index += 1) {
    const event = recent[index];
    if (event.type !== "pass" || event.completed !== false || !isDefensiveThird(event, match.homeTeam)) continue;
    const possessionChange = recent.slice(index + 1).find((candidate) =>
      candidate.matchTime - event.matchTime <= 45 &&
      candidate.fromTeam === event.team &&
      candidate.fromPlayer === event.player,
    );
    if (!possessionChange) continue;
    const evidence = turnoversByTeam.get(event.team) ?? [];
    evidence.push(event, possessionChange);
    turnoversByTeam.set(event.team, evidence);
  }
  const insights: SimulationInsight[] = [];

  for (const [team, evidence] of turnoversByTeam) {
    if (evidence.length < 6) continue;
    const supporting = evidence.slice(-6);
    const observation = copy.turnoverObservation(team, supporting.length / 2);
    insights.push({
      id: `${match.id}-turnovers-${supporting[0].id}-${last(supporting)?.id}-${teamFilter}-${playerFilter}-${audience}-${language}`,
      match_id: match.id,
      match_time: currentTime,
      valid_until: last(supporting)!.matchTime + 600,
      headline: copy.turnover,
      explanation: observation,
      supporting_event_ids: [...new Set(supporting.map((event) => event.id))],
      audience_mode: audience,
      language,
      observation,
      hypothesis: copy.turnoverHypothesis,
      team,
      player: "",
    });
  }

  const recentPressure = new Map<string, SimulationEvent[]>();
  const priorPressure = new Map<string, SimulationEvent[]>();
  for (const event of recent) {
    if (event.type !== "pressure") continue;
    const pressureEvents = recentPressure.get(event.team) ?? [];
    pressureEvents.push(event);
    recentPressure.set(event.team, pressureEvents);
  }
  for (const event of prior) {
    if (event.type !== "pressure") continue;
    const pressureEvents = priorPressure.get(event.team) ?? [];
    pressureEvents.push(event);
    priorPressure.set(event.team, pressureEvents);
  }
  for (const [team, currentWindow] of recentPressure) {
    const previousWindow = priorPressure.get(team) ?? [];
    const delta = currentWindow.length - previousWindow.length;
    if (currentWindow.length < 3 || previousWindow.length < 3 || delta < 3) continue;
    const supporting = currentWindow.slice(-4);
    const observation = copy.pressure(team, delta);
    insights.push({
      id: `${match.id}-pressure-${supporting[0].id}-${last(supporting)?.id}-${teamFilter}-${playerFilter}-${audience}-${language}`,
      match_id: match.id,
      match_time: currentTime,
      valid_until: last(supporting)!.matchTime + 600,
      headline: language === "es" ? "Cambio en la presión" : "Pressure has shifted",
      explanation: observation,
      supporting_event_ids: supporting.map((event) => event.id),
      audience_mode: audience,
      language,
      observation,
      hypothesis: copy.pressureHypothesis,
      team,
      player: "",
    });
  }

  if (insights.length === 0 && recent.length >= 8) {
    const bestPlayer = calculateSimulationStats(recent, match.homeTeam).playerPerformance[0];
    const observation = copy.defaultObservation(recent.length);
    insights.push({
      id: `${match.id}-activity-${recent[0].id}-${last(recent)?.id}-${teamFilter}-${playerFilter}-${audience}-${language}`,
      match_id: match.id,
      match_time: currentTime,
      valid_until: last(recent)!.matchTime + 480,
      headline: copy.defaultHeadline,
      explanation: observation,
      supporting_event_ids: recent.slice(-4).map((event) => event.id),
      audience_mode: audience,
      language,
      observation,
      hypothesis: copy.defaultHypothesis,
      team: bestPlayer?.team ?? "",
      player: bestPlayer?.player ?? "",
    });
  }

  return insights
    .filter((insight) => insight.valid_until >= currentTime)
    .sort((first, second) => {
      const firstFollowed = first.player && first.player === followedPlayer ? 1 : 0;
      const secondFollowed = second.player && second.player === followedPlayer ? 1 : 0;
      const firstFavorite = first.team === favoriteTeam ? 1 : 0;
      const secondFavorite = second.team === favoriteTeam ? 1 : 0;
      return secondFollowed - firstFollowed || secondFavorite - firstFavorite ||
        second.supporting_event_ids.length - first.supporting_event_ids.length;
    });
}
