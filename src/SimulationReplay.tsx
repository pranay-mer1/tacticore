import { useEffect, useMemo, useState } from "react";
import {
  calculateSimulationStats,
  createSimulation,
  deriveSimulationInsights,
  filterSimulationEvents,
  type AudienceMode,
  type SimulationEvent,
  type SimulationInsight,
  type SimulationLanguage,
} from "./simulation";

type Explanation = { observation: string; hypothesis: string };
type Preferences = {
  audience: AudienceMode;
  language: SimulationLanguage;
  favoriteTeam: string;
  followedPlayer: string;
};

const PREFERENCES_KEY = "tacticore.simulation.preferences.v1";
const INSIGHT_CACHE_KEY = "tacticore.simulation.insights.v1";
const STRUCTURED_INSIGHT_CACHE_KEY = "tacticore.simulation.structured-insights.v1";

function last<T>(items: T[]): T | undefined {
  return items[items.length - 1];
}

const initialPreferences: Preferences = {
  audience: "analyst",
  language: "en",
  favoriteTeam: "all",
  followedPlayer: "",
};

function readPreferences(): Preferences {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? "null");
    if (!value || typeof value !== "object") return initialPreferences;
    const item = value as Record<string, unknown>;
    return {
      audience: item.audience === "fan" ? "fan" : "analyst",
      language: item.language === "es" ? "es" : "en",
      favoriteTeam: typeof item.favoriteTeam === "string" ? item.favoriteTeam : "all",
      followedPlayer: typeof item.followedPlayer === "string" ? item.followedPlayer : "",
    };
  } catch {
    return initialPreferences;
  }
}

function getCachedExplanation(insightId: string): Explanation | undefined {
  try {
    const cache: unknown = JSON.parse(localStorage.getItem(INSIGHT_CACHE_KEY) ?? "{}");
    if (!cache || typeof cache !== "object") return undefined;
    const value = (cache as Record<string, unknown>)[insightId];
    if (!value || typeof value !== "object") return undefined;
    const explanation = value as Record<string, unknown>;
    if (typeof explanation.observation !== "string" || typeof explanation.hypothesis !== "string") return undefined;
    return { observation: explanation.observation, hypothesis: explanation.hypothesis };
  } catch {
    return undefined;
  }
}

function readStructuredInsightCache(): Record<string, SimulationInsight> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STRUCTURED_INSIGHT_CACHE_KEY) ?? "[]");
    if (!Array.isArray(value)) return {};
    return Object.fromEntries(value.filter((item): item is SimulationInsight =>
      !!item && typeof item === "object" &&
      typeof item.id === "string" &&
      typeof item.match_id === "string" &&
      typeof item.match_time === "number" &&
      typeof item.valid_until === "number" &&
      typeof item.headline === "string" &&
      typeof item.explanation === "string" &&
      Array.isArray(item.supporting_event_ids) &&
      (item.audience_mode === "analyst" || item.audience_mode === "fan") &&
      (item.language === "en" || item.language === "es") &&
      typeof item.observation === "string" &&
      typeof item.hypothesis === "string" &&
      typeof item.team === "string" &&
      typeof item.player === "string"
    ).map((item) => [item.id, item]));
  } catch {
    return {};
  }
}

function eventLabel(event: SimulationEvent): string {
  switch (event.type) {
    case "pass": return event.completed ? "Completed pass" : "Turnover pass";
    case "shot": return `Shot · ${event.outcome}`;
    case "tackle": return event.completed ? "Won tackle" : "Tackle";
    case "possession": return "Possession changed";
    case "pressure": return "Pressure";
    case "substitution": return `Substitution · ${event.substitutedPlayer ?? "player off"}`;
  }
}

function timeLabel(seconds: number): string {
  const minute = Math.floor(seconds / 60);
  const second = seconds % 60;
  return `${minute}'${String(second).padStart(2, "0")}`;
}

function matchingEvidence(insight: SimulationInsight, events: SimulationEvent[]): SimulationEvent[] {
  const ids = new Set(insight.supporting_event_ids);
  return events.filter((event) => ids.has(event.id));
}

export default function SimulationReplay() {
  const [seed, setSeed] = useState(20261015);
  const match = useMemo(() => createSimulation(seed), [seed]);
  const [eventCount, setEventCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [preferences, setPreferences] = useState(readPreferences);
  const [structuredInsightCache, setStructuredInsightCache] = useState(readStructuredInsightCache);
  const [teamFilter, setTeamFilter] = useState("all");
  const [playerFilter, setPlayerFilter] = useState("");
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({});
  const [explainingId, setExplainingId] = useState("");
  const [explainErrors, setExplainErrors] = useState<Record<string, string>>({});
  const [backendConfigured, setBackendConfigured] = useState<boolean | null>(null);

  const receivedEvents = useMemo(() => match.events.slice(0, eventCount), [match.events, eventCount]);
  const currentEvent = last(receivedEvents);
  const currentTime = currentEvent?.matchTime ?? 0;
  const filteredEvents = useMemo(
    () => filterSimulationEvents(receivedEvents, teamFilter, playerFilter),
    [receivedEvents, teamFilter, playerFilter],
  );
  const stats = useMemo(() => calculateSimulationStats(filteredEvents, match.homeTeam), [filteredEvents, match.homeTeam]);
  const derivedInsights = useMemo(
    () => deriveSimulationInsights(
      match,
      receivedEvents,
      preferences.audience,
      preferences.language,
      teamFilter,
      playerFilter,
      preferences.favoriteTeam,
      preferences.followedPlayer,
    ),
    [match, receivedEvents, preferences, teamFilter, playerFilter],
  );
  const insights = useMemo(
    () => derivedInsights.map((insight) => structuredInsightCache[insight.id] ?? insight),
    [derivedInsights, structuredInsightCache],
  );
  const playerNames = useMemo(
    () => [...new Set(Object.values(match.lineups).flat())].sort((first, second) => first.localeCompare(second)),
    [match.lineups],
  );
  const currentLineups = useMemo(() => {
    const lineups = Object.fromEntries(
      Object.entries(match.lineups).map(([team, players]) => [team, [...players]]),
    );
    for (const event of receivedEvents) {
      if (event.type !== "substitution" || !event.substitutedPlayer) continue;
      const teamPlayers = lineups[event.team];
      const outgoingIndex = teamPlayers?.indexOf(event.substitutedPlayer) ?? -1;
      if (outgoingIndex >= 0) teamPlayers[outgoingIndex] = event.player;
    }
    return lineups;
  }, [match.lineups, receivedEvents]);
  const latestEvents = filteredEvents.slice(-12).reverse();
  const goals = receivedEvents.filter((event) => event.type === "shot" && event.outcome === "Goal");
  const homeGoals = goals.filter((event) => event.team === match.homeTeam).length;
  const awayGoals = goals.filter((event) => event.team === match.awayTeam).length;
  const completed = eventCount >= match.events.length;
  const halfTimeReached = currentTime >= 45 * 60;

  useEffect(() => {
    try {
      localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
    } catch {
      setExplainErrors((current) => ({ ...current, preferences: "Preferences could not be saved in this browser." }));
    }
  }, [preferences]);

  useEffect(() => {
    if (derivedInsights.length === 0) return;
    setStructuredInsightCache((current) => {
      const next = { ...current };
      for (const insight of derivedInsights) next[insight.id] ??= insight;
      if (Object.keys(next).length === Object.keys(current).length) return current;
      const retained = Object.values(next).slice(-200);
      try {
        localStorage.setItem(STRUCTURED_INSIGHT_CACHE_KEY, JSON.stringify(retained));
        return Object.fromEntries(retained.map((insight) => [insight.id, insight]));
      } catch {
        setExplainErrors((errors) => ({ ...errors, cache: "Generated insight cache could not be saved in this browser." }));
        return next;
      }
    });
  }, [derivedInsights]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/foundry/status")
      .then((response) => response.json())
      .then((value: unknown) => {
        if (!cancelled && value && typeof value === "object" && typeof (value as Record<string, unknown>).configured === "boolean") {
          setBackendConfigured((value as Record<string, boolean>).configured);
        }
      })
      .catch(() => {
        if (!cancelled) setBackendConfigured(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setEventCount((count) => {
        const next = Math.min(match.events.length, count + speed);
        if (next >= match.events.length) setPlaying(false);
        return next;
      });
    }, 420);
    return () => window.clearInterval(timer);
  }, [playing, speed, match.events.length]);

  const updatePreference = <K extends keyof Preferences>(key: K, value: Preferences[K]) => {
    setPreferences((current) => ({ ...current, [key]: value }));
  };

  const resetReplay = () => {
    setPlaying(false);
    setEventCount(0);
    setExplanations({});
    setExplainErrors({});
  };

  const seekEvent = (event: SimulationEvent) => {
    const index = match.events.findIndex((candidate) => candidate.id === event.id);
    if (index >= 0) {
      setPlaying(false);
      setEventCount(index + 1);
    }
  };

  const startNewSeed = () => {
    setPlaying(false);
    setEventCount(0);
    setExplanations({});
    setExplainErrors({});
    setSeed((current) => current + 1);
  };

  const askFoundry = async (insight: SimulationInsight) => {
    setExplainingId(insight.id);
    setExplainErrors((current) => ({ ...current, [insight.id]: "" }));
    const evidence = matchingEvidence(insight, filteredEvents);
    try {
      const response = await fetch("/api/foundry/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          insight,
          statistics: stats,
          current_match_time: currentTime,
          filters: { team: teamFilter, player: playerFilter },
          evidence_events: evidence.map(({ id, matchTime, team, player, type, x, y, completed, outcome, fromTeam, fromPlayer }) => ({
            id, matchTime, team, player, type, x, y, completed, outcome, fromTeam, fromPlayer,
          })),
        }),
      });
      const value: unknown = await response.json();
      if (!response.ok) {
        const message = value && typeof value === "object" && typeof (value as Record<string, unknown>).error === "string"
          ? (value as Record<string, string>).error
          : `Foundry request failed (HTTP ${response.status}).`;
        throw new Error(message);
      }
      if (!value || typeof value !== "object" ||
        typeof (value as Record<string, unknown>).observation !== "string" ||
        typeof (value as Record<string, unknown>).hypothesis !== "string") {
        throw new Error("Foundry returned an invalid explanation; the event-based insight remains available.");
      }
      const explanation = {
        observation: (value as Record<string, string>).observation,
        hypothesis: (value as Record<string, string>).hypothesis,
      };
      setExplanations((current) => ({ ...current, [insight.id]: explanation }));
      const previous: unknown = JSON.parse(localStorage.getItem(INSIGHT_CACHE_KEY) ?? "{}");
      const cache = previous && typeof previous === "object" ? previous as Record<string, Explanation> : {};
      localStorage.setItem(INSIGHT_CACHE_KEY, JSON.stringify({ ...cache, [insight.id]: explanation }));
    } catch (cause) {
      setExplainErrors((current) => ({
        ...current,
        [insight.id]: cause instanceof Error ? cause.message : "AI explanation failed. The deterministic insight is still available.",
      }));
    } finally {
      setExplainingId("");
    }
  };

  const copy = preferences.language === "es"
    ? {
      title: "Simulación sintética de partido",
      description: "Generador determinista · eventos progresivos · análisis sin acceso a eventos futuros",
      received: "EVENTOS RECIBIDOS",
      clock: "RELOJ DE PARTIDO",
      play: "Reproducir",
      pause: "Pausar",
      step: "Siguiente evento",
      reset: "Reiniciar",
      newSeed: "Nueva simulación",
      speed: "VELOCIDAD",
      audience: "MODO",
      analyst: "Analista",
      fan: "Aficionado",
      language: "IDIOMA",
      favoriteTeam: "EQUIPO FAVORITO",
      followedPlayer: "JUGADOR SEGUIDO",
      allTeams: "Todos los equipos",
      noPlayer: "Ninguno",
      passes: "PASES",
      accuracy: "PRECISIÓN",
      shots: "TIROS",
      tackles: "ENTRADAS",
      zones: "ZONAS DE ATAQUE",
      timeline: "CRONOLOGÍA DE EVENTOS",
      insights: "HALLAZGOS EN VIVO",
      analystLabel: "ANALISTA",
      fanLabel: "AFICIONADO",
      observation: "Observación basada en eventos",
      hypothesis: "Hipótesis táctica",
      fanTurnover: "Se repitieron las pérdidas en su zona defensiva.",
      fanPressure: "El equipo aplicó más presión durante este tramo.",
      fanActivity: "El partido tuvo un tramo activo.",
      fanHypothesis: "Una posible explicación táctica, todavía por confirmar.",
      askAi: "Explicar con Foundry",
      explainUnavailable: "Explicación de IA no configurada; el hallazgo basado en eventos sigue disponible.",
      noInsights: "Se necesitan más eventos para mostrar un patrón. Umbrales activos: tres pérdidas defensivas o una ventana de presión con evidencia suficiente.",
      halftime: "RESUMEN DEL DESCANSO",
      fulltime: "RESUMEN FINAL",
      evidence: "Evidencia",
      empty: "Inicia la reproducción para recibir eventos y calcular estadísticas.",
      filterNote: "Los filtros limitan estadísticas, hallazgos y evidencia enviada a Foundry.",
    }
    : {
      title: "Synthetic match simulation",
      description: "Repeatable generator · progressive events · analysis cannot access future replay events",
      received: "EVENTS RECEIVED",
      clock: "MATCH CLOCK",
      play: "Play",
      pause: "Pause",
      step: "Step event",
      reset: "Reset",
      newSeed: "New simulation",
      speed: "SPEED",
      audience: "MODE",
      analyst: "Analyst",
      fan: "Fan",
      language: "LANGUAGE",
      favoriteTeam: "FAVOURITE TEAM",
      followedPlayer: "FOLLOWED PLAYER",
      allTeams: "All teams",
      noPlayer: "None",
      passes: "PASSES",
      accuracy: "PASS ACCURACY",
      shots: "SHOTS",
      tackles: "TACKLES",
      zones: "ATTACKING ZONES",
      timeline: "EVENT TIMELINE",
      insights: "LIVE INSIGHTS",
      analystLabel: "ANALYST",
      fanLabel: "FAN",
      observation: "Event-based observation",
      hypothesis: "Tactical hypothesis",
      fanTurnover: "Possession was lost repeatedly in the defensive area.",
      fanPressure: "The team applied more pressure during this spell.",
      fanActivity: "The match had a busy spell.",
      fanHypothesis: "A possible tactical explanation, not yet confirmed.",
      askAi: "Explain with Foundry",
      explainUnavailable: "AI explanation is not configured; the event-based insight is still available.",
      noInsights: "More events are needed before showing a pattern. Active thresholds: three defensive turnovers or a pressure window with sufficient evidence.",
      halftime: "HALF-TIME RECAP",
      fulltime: "FULL-TIME RECAP",
      evidence: "Evidence",
      empty: "Start replay to receive events and calculate statistics.",
      filterNote: "Filters limit statistics, insights, and evidence sent to Foundry.",
    };

  const recap = (label: string, events: SimulationEvent[]) => {
    if (events.length === 0) return null;
    const latestShot = [...events].reverse().find((event) => event.type === "shot");
    const standout = calculateSimulationStats(events, match.homeTeam).playerPerformance[0];
    const claimEventIds = [
      ...(latestShot ? [latestShot.id] : []),
      ...(standout ? events.filter((event) => event.player === standout.player && event.team === standout.team).slice(-2).map((event) => event.id) : []),
    ];
    const uniqueIds = [...new Set(claimEventIds)];
    return <article className="recap-card" key={label}>
      <div className="simulation-kicker">{label} · CLAIMS LINK TO EVENTS</div>
      <p>{latestShot
        ? preferences.language === "es"
          ? `${latestShot.team}: ${latestShot.outcome === "Goal" ? "un gol registrado" : `un tiro ${latestShot.outcome?.toLowerCase() ?? ""}`} en ${timeLabel(latestShot.matchTime)}.`
          : `${latestShot.team}: ${latestShot.outcome === "Goal" ? "a recorded goal" : `a ${latestShot.outcome?.toLowerCase() ?? "shot"}`} at ${timeLabel(latestShot.matchTime)}.`
        : preferences.language === "es" ? "No se registraron tiros en este periodo." : "No shot event has been recorded in this period."}</p>
      {standout && <p>{preferences.language === "es"
        ? `${standout.player} (${standout.team}) encabeza las acciones registradas con ${standout.actions} eventos.`
        : `${standout.player} (${standout.team}) leads the recorded action count with ${standout.actions} events.`}</p>}
      <div className="evidence-links">{uniqueIds.map((id) => {
        const evidenceEvent = events.find((event) => event.id === id);
        return evidenceEvent ? <button key={id} onClick={() => seekEvent(evidenceEvent)}>{timeLabel(evidenceEvent.matchTime)} · {eventLabel(evidenceEvent)}</button> : null;
      })}</div>
    </article>;
  };

  return (
    <section className="simulation-workspace" aria-label="Synthetic match simulation">
      <header className="simulation-header">
        <div>
          <div className="simulation-kicker">INGEST → INTERPRET → EXPLAIN → RENDER → PERSONALIZE</div>
          <h2>{copy.title}</h2>
          <p>{copy.description}</p>
        </div>
        <span className="simulation-badge">SYNTHETIC · NOT LIVE</span>
      </header>

      <section className="simulation-matchbar">
        <div><strong>{match.homeTeam}</strong><span>{homeGoals} : {awayGoals}</span><strong>{match.awayTeam}</strong></div>
        <small>{match.competition} · {match.venue} · seed {seed}</small>
      </section>
      <section className="simulation-lineups" aria-label="Starting lineups">
        {Object.entries(currentLineups).map(([teamName, players]) => <div key={teamName}>
          <strong>{teamName} · Current XI</strong>
          <span>{players.map((player) => <i key={player} className={player === currentEvent?.player ? "lineup-current" : ""}>{player}</i>)}</span>
        </div>)}
      </section>

      <section className="replay-controls" aria-label="Replay controls">
        <div className="replay-actions">
          <button className="replay-primary" onClick={() => {
            if (completed) setEventCount(0);
            setPlaying((current) => !current);
          }} disabled={match.events.length === 0}>{playing ? copy.pause : copy.play}</button>
          <button onClick={() => { setPlaying(false); setEventCount((count) => Math.min(match.events.length, count + 1)); }} disabled={completed}>{copy.step}</button>
          <button onClick={resetReplay}>{copy.reset}</button>
          <button onClick={startNewSeed}>{copy.newSeed}</button>
        </div>
        <label className="simulation-select"><span>{copy.speed}</span>
          <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
            <option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option>
          </select>
        </label>
        <div className="replay-progress">
          <span>{copy.clock}</span><strong>{currentEvent ? timeLabel(currentTime) : "00'00"}</strong>
          <input type="range" aria-label="Replay position" min="0" max={match.events.length} value={eventCount}
            onChange={(event) => { setPlaying(false); setEventCount(Number(event.target.value)); }} />
          <span>{eventCount} / {match.events.length} {copy.received.toLowerCase()}</span>
        </div>
      </section>

      <section className="personalization-panel">
        <label className="simulation-select"><span>{copy.audience}</span>
          <select value={preferences.audience} onChange={(event) => updatePreference("audience", event.target.value as AudienceMode)}>
            <option value="analyst">{copy.analyst}</option><option value="fan">{copy.fan}</option>
          </select>
        </label>
        <label className="simulation-select"><span>{copy.language}</span>
          <select value={preferences.language} onChange={(event) => updatePreference("language", event.target.value as SimulationLanguage)}>
            <option value="en">English</option><option value="es">Español</option>
          </select>
        </label>
        <label className="simulation-select"><span>{copy.favoriteTeam}</span>
          <select value={preferences.favoriteTeam} onChange={(event) => updatePreference("favoriteTeam", event.target.value)}>
            <option value="all">{copy.allTeams}</option><option>{match.homeTeam}</option><option>{match.awayTeam}</option>
          </select>
        </label>
        <label className="simulation-select"><span>{copy.followedPlayer}</span>
          <select value={preferences.followedPlayer} onChange={(event) => updatePreference("followedPlayer", event.target.value)}>
            <option value="">{copy.noPlayer}</option>{playerNames.map((player) => <option key={player}>{player}</option>)}
          </select>
        </label>
        <span className="filter-note">{copy.filterNote}</span>
      </section>

      <div className="simulation-stat-grid">
        <article><span>{copy.passes}</span><strong>{stats.passes}</strong><small>{stats.completedPasses} / {stats.passes} complete</small></article>
        <article><span>{copy.accuracy}</span><strong>{stats.passAccuracy === null ? "—" : `${stats.passAccuracy}%`}</strong><small>received events only</small></article>
        <article><span>{copy.shots}</span><strong>{stats.shots}</strong><small>{stats.shotsOnTarget} on target</small></article>
        <article><span>{copy.tackles}</span><strong>{stats.tackles}</strong><small>{stats.turnovers} defensive-third turnovers</small></article>
      </div>

      <div className="simulation-grid">
        <section className="simulation-panel pitch-panel">
          <header><div><div className="simulation-kicker">LIVE RENDER</div><h3>Event map</h3></div>
            <span className="current-player">{currentEvent ? `${currentEvent.player} · ${currentEvent.team}` : "No current event"}</span></header>
          <svg className="synthetic-pitch" viewBox="0 0 1000 600" role="img" aria-label="2D pitch showing received synthetic events only">
            <rect x="18" y="18" width="964" height="564" rx="6" />
            <line x1="500" y1="18" x2="500" y2="582" />
            <circle cx="500" cy="300" r="78" />
            <circle cx="500" cy="300" r="4" className="pitch-mark" />
            <rect x="18" y="153" width="145" height="294" /><rect x="18" y="226" width="56" height="148" />
            <rect x="837" y="153" width="145" height="294" /><rect x="926" y="226" width="56" height="148" />
            <path d="M163 248 A76 76 0 0 1 163 352" /><path d="M837 248 A76 76 0 0 0 837 352" />
            {receivedEvents.slice(-32).map((event) => (
              <circle key={event.id} className={`pitch-event ${event.type} ${event.id === currentEvent?.id ? "active" : ""} ${currentEvent?.player === event.player ? "player-highlight" : ""}`}
                cx={event.x * 10} cy={event.y * 6} r={event.id === currentEvent?.id ? 10 : 6}
                fill={event.team === match.homeTeam ? "#68dfbf" : "#a995ff"}>
                <title>{timeLabel(event.matchTime)} · {eventLabel(event)} · {event.player} · {event.team}</title>
              </circle>
            ))}
            {currentEvent && <text x={currentEvent.x * 10 + 14} y={currentEvent.y * 6 - 12} className="pitch-player-label">{currentEvent.player}</text>}
          </svg>
          <div className="pitch-legend"><span><i className="home-legend" /> {match.homeTeam}</span><span><i className="away-legend" /> {match.awayTeam}</span><small>Coordinates are illustrative synthetic event locations, not tracking data.</small></div>
        </section>

        <section className="simulation-panel insights-panel">
          <header><div><div className="simulation-kicker">INTERPRET → EXPLAIN</div><h3>{copy.insights}</h3></div>
            <span className="insight-count">{insights.length}</span></header>
          {backendConfigured === false && <div className="foundry-status">{copy.explainUnavailable}</div>}
          {insights.length === 0 && <p className="insights-empty">{copy.noInsights}</p>}
          <div className="insight-stack">
            {insights.map((insight) => {
              const cached = explanations[insight.id] ?? getCachedExplanation(insight.id);
              const displayedObservation = cached?.observation ?? insight.observation;
              const displayedHypothesis = cached?.hypothesis ?? insight.hypothesis;
              const fanObservation = insight.id.includes("-turnovers-")
                ? copy.fanTurnover
                : insight.id.includes("-pressure-") ? copy.fanPressure : copy.fanActivity;
              return <article className="insight-card" key={insight.id} data-insight-id={insight.id}>
                <div className="insight-card-top"><strong>{insight.headline}</strong><span>EXPIRES {timeLabel(insight.valid_until)}</span></div>
                <div className="insight-structured" data-match-id={insight.match_id} data-match-time={insight.match_time}
                  data-valid-until={insight.valid_until} data-audience-mode={insight.audience_mode} data-language={insight.language}>
                  <div><b>{copy.observation}</b><p>{preferences.audience === "fan"
                    ? insight.id.includes("-pressure-") && insight.team
                      ? `${insight.team} · ${fanObservation}`
                      : fanObservation
                    : displayedObservation}</p>
                    {(insight.team || (preferences.audience === "analyst" && insight.player)) &&
                      <small>{[insight.team, preferences.audience === "analyst" ? insight.player : ""].filter(Boolean).join(" · ")}</small>}</div>
                  <div><b>{copy.hypothesis}</b><p>{preferences.audience === "fan" ? copy.fanHypothesis : displayedHypothesis}</p></div>
                </div>
                <div className="insight-evidence"><span>{copy.evidence}:</span>{matchingEvidence(insight, filteredEvents).map((event) =>
                  <button key={event.id} onClick={() => seekEvent(event)}>{timeLabel(event.matchTime)} · {event.player}</button>)}</div>
                <button className="foundry-button" disabled={explainingId === insight.id || backendConfigured === false}
                  onClick={() => void askFoundry(insight)}>{explainingId === insight.id ? "Explaining…" : copy.askAi}</button>
                {explainErrors[insight.id] && <p className="explain-error" role="alert">{explainErrors[insight.id]}</p>}
              </article>;
            })}
          </div>
        </section>

        <section className="simulation-panel">
          <header><div><div className="simulation-kicker">INTERPRET</div><h3>Player performance</h3></div></header>
          <div className="simulation-player-table">
            <div className="simulation-player-row table-header"><span>PLAYER</span><span>ACTIONS</span><span>PASSES</span><span>SHOTS</span><span>TACKLES</span></div>
            {stats.playerPerformance.slice(0, 8).map((player) =>
              <div className="simulation-player-row" key={`${player.team}:${player.player}`}>
                <span><b>{player.player}</b><small>{player.team}</small></span><span>{player.actions}</span>
                <span>{player.passes}</span><span>{player.shots}</span><span>{player.tackles}</span>
              </div>)}
            {stats.playerPerformance.length === 0 && <p className="simulation-empty">{copy.empty}</p>}
          </div>
        </section>

        <section className="simulation-panel">
          <header><div><div className="simulation-kicker">INTERPRET</div><h3>{copy.zones}</h3></div></header>
          <div className="zone-bars">
            {(["left", "central", "right"] as const).map((zone) => {
              const count = stats.attackingZones[zone];
              const maximum = Math.max(1, ...Object.values(stats.attackingZones));
              return <div className="zone-row" key={zone}><span>{zone}</span><div><i style={{ width: `${(count / maximum) * 100}%` }} /></div><b>{count}</b></div>;
            })}
          </div>
          <p className="simulation-footnote">Based only on received shot locations, oriented to the attacking team's direction.</p>
        </section>

        <section className="simulation-panel timeline-panel-sim">
          <header><div><div className="simulation-kicker">RENDER</div><h3>{copy.timeline}</h3></div>
            <label className="simulation-select"><span>TEAM FILTER</span>
              <select value={teamFilter} onChange={(event) => setTeamFilter(event.target.value)}>
                <option value="all">{copy.allTeams}</option><option>{match.homeTeam}</option><option>{match.awayTeam}</option>
              </select>
            </label>
            <label className="simulation-select"><span>PLAYER FILTER</span>
              <input value={playerFilter} onChange={(event) => setPlayerFilter(event.target.value)} placeholder="Search player" />
            </label>
          </header>
          <p className="filter-note">{copy.filterNote}</p>
          <div className="sim-timeline">
            {latestEvents.map((event) => <button key={event.id} className={`sim-event ${event.id === currentEvent?.id ? "current" : ""}`}
              onClick={() => seekEvent(event)}>
              <span className={`sim-event-dot ${event.type}`} /><time>{timeLabel(event.matchTime)}</time>
              <span className="sim-event-main"><b>{eventLabel(event)}</b><small>{event.player} · {event.team}</small></span>
            </button>)}
            {latestEvents.length === 0 && <p className="simulation-empty">{copy.empty}</p>}
          </div>
        </section>

        <section className="recap-grid">
          {halfTimeReached && recap(copy.halftime, filteredEvents.filter((event) => event.matchTime <= 45 * 60))}
          {completed && recap(copy.fulltime, filteredEvents)}
        </section>
      </div>
      <footer className="simulation-footer">
        {eventCount} of {match.events.length} generated events received · only the received, filtered events are used for statistics, insight evidence, and Foundry context.
        {explainErrors.preferences && <span role="alert">{explainErrors.preferences}</span>}
        {explainErrors.cache && <span role="alert">{explainErrors.cache}</span>}
        {backendConfigured === true && <span>Microsoft Foundry connection configured in the local backend.</span>}
      </footer>
    </section>
  );
}
