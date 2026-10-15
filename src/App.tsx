import { useEffect, useMemo, useRef, useState } from "react";
import eventData from "./data/events.json";
import MatchLibrary, { type CollectionMatch } from "./MatchLibrary";
import SimulationReplay from "./SimulationReplay";
import type { EventType, FootballEvent, FootballMatch } from "./types";

type SortKey = "passes" | "shots" | "tackles" | "goals";
type DataSource = "synthetic" | "statsbomb" | "results-archive" | "wyscout";
type PlayerStats = {
  name: string;
  team: string;
  passes: number;
  knownPasses: number;
  completedPasses: number;
  missingPassData: number;
  shots: number;
  goals: number;
  tackles: number;
};
type HistoricalSummary = {
  id: string;
  date: string;
  competition: string;
  homeTeam: string;
  awayTeam: string;
  file: string;
  cacheKey?: string;
  source: "statsbomb-open-data" | "user-results-archive" | "wyscout-open-data";
};
type SyntheticEvent = {
  minute: number;
  team: string;
  player: string;
  type: "pass" | "shot" | "tackle";
  completed?: boolean;
  successful?: boolean;
  outcome?: string;
};
type SyntheticMatch = Omit<FootballMatch, "source" | "status" | "events"> & {
  events: SyntheticEvent[];
};

const syntheticMatches: FootballMatch[] = (eventData.matches as SyntheticMatch[]).map((match) => ({
  ...match,
  source: "synthetic",
  status: "synthetic",
  events: match.events.map((event, index): FootballEvent => ({
    ...event,
    eventId: `synthetic:${match.id}:${index}`,
    onTarget: event.type === "shot" ? event.outcome !== "off target" : undefined,
  })),
}));

function getPlayerStats(
  events: FootballEvent[],
  lineups: FootballMatch["lineups"] = [],
): PlayerStats[] {
  const byPlayer = new Map<string, PlayerStats>();
  for (const lineup of lineups ?? []) {
    for (const name of lineup.players) {
      if (!byPlayer.has(name)) {
        byPlayer.set(name, {
          name,
          team: lineup.team,
          passes: 0,
          knownPasses: 0,
          completedPasses: 0,
          missingPassData: 0,
          shots: 0,
          goals: 0,
          tackles: 0,
        });
      }
    }
  }
  for (const event of events) {
    if (!event.player) continue;
    const player = byPlayer.get(event.player) ?? {
      name: event.player,
      team: event.team,
      passes: 0,
      knownPasses: 0,
      completedPasses: 0,
      missingPassData: 0,
      shots: 0,
      goals: 0,
      tackles: 0,
    };
    if (event.type === "pass") {
      player.passes += 1;
      if (event.completed === true) {
        player.completedPasses += 1;
        player.knownPasses += 1;
      } else if (event.completed === false) {
        player.knownPasses += 1;
      } else {
        player.missingPassData += 1;
      }
    } else if (event.type === "shot") {
      player.shots += 1;
      if (event.outcome?.toLowerCase() === "goal" && !event.goalOwnGoal) player.goals += 1;
    } else if (event.type === "goal") {
      if (!event.goalOwnGoal) player.goals += 1;
    } else if (event.type === "tackle") {
      player.tackles += 1;
    }
    byPlayer.set(event.player, player);
  }
  return [...byPlayer.values()];
}

function goalsFor(events: FootballEvent[], teamName: string): number {
  return events.filter((event) =>
    event.type === "shot" &&
    (event.goalTeam ?? event.team) === teamName &&
    event.outcome?.toLowerCase() === "goal"
  ).length;
}

function accuracyLabel(events: FootballEvent[]): string {
  const passes = events.filter((event) => event.type === "pass");
  const known = passes.filter((event) => event.completed !== null && event.completed !== undefined);
  if (known.length === 0) return "—";
  const complete = known.filter((event) => event.completed === true).length;
  return `${Math.round((complete / known.length) * 100)}%`;
}

function getEventTitle(event: FootballEvent): string {
  switch (event.type) {
    case "pass":
      return event.completed === null || event.completed === undefined
        ? "Pass result unavailable"
        : event.completed ? "Completed pass" : "Incomplete pass";
    case "shot":
      return event.outcome ? `Shot · ${event.outcome}` : "Shot outcome unavailable";
    case "tackle":
      return event.successful ? "Won tackle" : "Tackle";
    case "goal":
      return event.goalOwnGoal ? "Own goal recorded" : "Goal recorded";
    case "other":
      return event.sourceEventName ?? "Other event";
  }
}

function EventMark({ type }: { type: EventType }) {
  const symbol = type === "pass" ? "↗" : type === "shot" ? "◉" : type === "tackle" ? "▰" : type === "goal" ? "⚽" : "·";
  return <span className={`event-mark ${type}`} aria-hidden="true">{symbol}</span>;
}

function isHistoricalSummary(value: unknown): value is HistoricalSummary {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" &&
    typeof item.date === "string" &&
    typeof item.competition === "string" &&
    typeof item.homeTeam === "string" &&
    typeof item.awayTeam === "string" &&
    (item.source === "statsbomb-open-data" || item.source === "user-results-archive" || item.source === "wyscout-open-data") &&
    typeof item.file === "string" &&
    item.file.startsWith("matches/") &&
    !item.file.includes("..");
}

function isHistoricalMatch(value: unknown): value is FootballMatch {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (item.source === "statsbomb-open-data" || item.source === "user-results-archive" || item.source === "wyscout-open-data") &&
    item.status === "historical" &&
    typeof item.id === "string" &&
    typeof item.homeTeam === "string" &&
    typeof item.awayTeam === "string" &&
    Array.isArray(item.events) &&
    item.events.every((event) =>
      !!event && typeof event === "object" &&
      typeof (event as Record<string, unknown>).eventId === "string"
    );
}

export default function App() {
  const [dataSource, setDataSource] = useState<DataSource>("synthetic");
  const [matchId, setMatchId] = useState(syntheticMatches[0].id);
  const [team, setTeam] = useState("All teams");
  const [playerSearch, setPlayerSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("passes");
  const [descending, setDescending] = useState(true);
  const [activeTab, setActiveTab] = useState("Overview");
  const [historicalMatches, setHistoricalMatches] = useState<HistoricalSummary[]>([]);
  const [historicalMatch, setHistoricalMatch] = useState<FootballMatch | null>(null);
  const [loadingIndex, setLoadingIndex] = useState(false);
  const [loadingMatch, setLoadingMatch] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const historyCache = useRef(new Map<string, FootballMatch>());
  const pendingOpenMatchId = useRef<string | null>(null);

  useEffect(() => {
    if (dataSource === "synthetic") return;
    const source = dataSource === "statsbomb"
      ? "statsbomb-open-data"
      : dataSource === "wyscout"
      ? "wyscout-open-data"
      : "user-results-archive";
    let cancelled = false;
    setLoadingIndex(true);
    setHistoryError("");
    fetch("/data/historical/index.json", { cache: "no-store" })
      .then(async (response) => {
        if (response.status === 404) return [];
        if (!response.ok) throw new Error(`Could not read the local match index (HTTP ${response.status}).`);
        if (response.headers.get("content-type")?.includes("text/html")) return [];
        const value: unknown = await response.json();
        if (!value || typeof value !== "object" || !Array.isArray((value as { matches?: unknown }).matches)) {
          throw new Error("The local historical match index has an invalid format.");
        }
        return (value as { matches: unknown[] }).matches
          .filter(isHistoricalSummary)
          .filter((item) => item.source === source);
      })
      .then((items) => {
        if (cancelled) return;
        setHistoricalMatches(items);
        const requestedId = pendingOpenMatchId.current;
        pendingOpenMatchId.current = null;
        setMatchId((current) => requestedId && items.some((item) => item.id === requestedId)
          ? requestedId
          : items.some((item) => item.id === current) ? current : items[0]?.id ?? "");
        setHistoricalMatch(null);
      })
      .catch((error: unknown) => {
        if (!cancelled) setHistoryError(error instanceof Error ? error.message : "Could not read local historical matches.");
      })
      .finally(() => {
        if (!cancelled) setLoadingIndex(false);
      });
    return () => { cancelled = true; };
  }, [dataSource, reloadKey]);

  useEffect(() => {
    if (dataSource === "synthetic" || !matchId) {
      setHistoricalMatch(null);
      return;
    }
    const summary = historicalMatches.find((item) => item.id === matchId);
    if (!summary) {
      setHistoricalMatch(null);
      return;
    }
    const cached = historyCache.current.get(summary.id);
    if (cached) {
      setHistoricalMatch(cached);
      return;
    }
    let cancelled = false;
    setLoadingMatch(true);
    setHistoryError("");
    const cacheVersion = summary.cacheKey ? `?v=${encodeURIComponent(summary.cacheKey)}` : "";
    fetch(`/data/historical/${summary.file}${cacheVersion}`, { cache: "force-cache" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Could not load imported match ${summary.id} (HTTP ${response.status}).`);
        const value: unknown = await response.json();
        if (!isHistoricalMatch(value)) throw new Error(`Imported match ${summary.id} has an invalid format.`);
        return value;
      })
      .then((value) => {
        if (cancelled) return;
        historyCache.current.set(summary.id, value);
        setHistoricalMatch(value);
      })
      .catch((error: unknown) => {
        if (!cancelled) setHistoryError(error instanceof Error ? error.message : "Could not load the imported match.");
      })
      .finally(() => {
        if (!cancelled) setLoadingMatch(false);
      });
    return () => { cancelled = true; };
  }, [dataSource, historicalMatches, matchId]);

  const match = dataSource === "synthetic"
    ? syntheticMatches.find((item) => item.id === matchId) ?? syntheticMatches[0]
    : historicalMatch?.id === matchId ? historicalMatch : null;
  const teams = match ? [match.homeTeam, match.awayTeam] : [];
  const filteredEvents = useMemo(
    () => (match?.events ?? []).filter((event) =>
      (team === "All teams" || event.team === team) &&
      (!playerSearch.trim() || event.player.toLowerCase().includes(playerSearch.trim().toLowerCase())),
    ),
    [match, team, playerSearch],
  );
  const allStats = useMemo(
    () => match ? getPlayerStats(match.events, match.lineups) : [],
    [match],
  );
  const visibleStats = useMemo(() => {
    const query = playerSearch.trim().toLowerCase();
    return allStats
      .filter((stat) => (team === "All teams" || stat.team === team) && stat.name.toLowerCase().includes(query))
      .sort((first, second) => {
        const difference = first[sortKey] - second[sortKey];
        return difference === 0
          ? first.name.localeCompare(second.name)
          : descending ? -difference : difference;
      });
  }, [allStats, team, playerSearch, sortKey, descending]);

  const events = match?.events ?? [];
  const homeTeam = match?.homeTeam ?? "";
  const awayTeam = match?.awayTeam ?? "";
  const homeScore = match?.source === "user-results-archive"
    ? match.officialScore?.home ?? null
    : goalsFor(events, homeTeam);
  const awayScore = match?.source === "user-results-archive"
    ? match.officialScore?.away ?? null
    : goalsFor(events, awayTeam);
  const selectedPasses = filteredEvents.filter((event) => event.type === "pass");
  const knownSelectedPasses = selectedPasses.filter((event) => event.completed !== null && event.completed !== undefined);
  const totalShots = filteredEvents.filter((event) => event.type === "shot");
  const knownShotsOnTarget = totalShots.filter((event) => event.onTarget !== null && event.onTarget !== undefined);
  const shotsOnTarget = knownShotsOnTarget.filter((event) => event.onTarget === true).length;
  const matchShots = events.filter((event) => event.type === "shot");
  const homeShots = matchShots.filter((event) => event.team === homeTeam).length;
  const awayShots = matchShots.filter((event) => event.team === awayTeam).length;
  const matchAccuracy = accuracyLabel(events);
  const supportsMetric = (metric: "goals" | "passes" | "shots" | "tackles") =>
    !match?.availableMetrics || match.availableMetrics.includes(metric);
  const clearFilters = () => {
    setTeam("All teams");
    setPlayerSearch("");
  };
  const selectSort = (key: SortKey) => {
    if (sortKey === key) setDescending((current) => !current);
    else {
      setSortKey(key);
      setDescending(true);
    }
  };
  const changeSource = (next: DataSource) => {
    setDataSource(next);
    setHistoricalMatch(null);
    clearFilters();
    if (next === "synthetic") setMatchId(syntheticMatches[0].id);
    else setMatchId("");
  };
  const openCollectionMatch = (item: CollectionMatch) => {
    const source: DataSource = item.source === "statsbomb-open-data"
      ? "statsbomb"
      : item.source === "wyscout-open-data" ? "wyscout" : "results-archive";
    setDataSource(source);
    setMatchId(item.id);
    setActiveTab("Overview");
    clearFilters();
  };
  const openImportedMatch = (id: string) => {
    historyCache.current.clear();
    pendingOpenMatchId.current = id;
    setDataSource("wyscout");
    setMatchId(id);
    setActiveTab("Overview");
    setReloadKey((key) => key + 1);
    clearFilters();
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setActiveTab("Overview"); }} aria-label="Tacticore home">
          <span className="brand-mark"><span /></span>
          <span className="brand-name">tacticore<span>.</span></span>
        </a>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          <button className={`nav-item ${activeTab === "Overview" ? "selected" : ""}`} onClick={() => setActiveTab("Overview")}>
            <span className="nav-icon">▦</span> Overview
          </button>
          <button className={`nav-item ${activeTab === "Matches" ? "selected" : ""}`} onClick={() => setActiveTab("Matches")}>
            <span className="nav-icon">◷</span> Matches
          </button>
          <button className={`nav-item ${activeTab === "Players" ? "selected" : ""}`} onClick={() => setActiveTab("Players")}>
            <span className="nav-icon">♙</span> Players
          </button>
          <button className={`nav-item ${activeTab === "Replay" ? "selected" : ""}`} onClick={() => setActiveTab("Replay")}>
            <span className="nav-icon">▶</span> Pipeline replay
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-divider" />
          <div className="workspace-label"><span className="workspace-dot" /> LOCAL WORKSPACE</div>
          <div className="profile">
            <div className="avatar">TC</div>
            <div><strong>Team analyst</strong><span>Local workspace</span></div>
            <span className="profile-menu">···</span>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><b>/</b><strong>{activeTab}</strong></div>
          <div className="topbar-right">
            <span className={`live-dot ${dataSource !== "synthetic" ? "historical-dot" : ""}`} />
            <span className="local-status">{dataSource !== "synthetic" ? "HISTORICAL · NOT LIVE" : "LOCAL DEMO"}</span>
            <button className="icon-button" aria-label="Notifications" onClick={() => window.alert("You’re all caught up.")}>♧<i /></button>
            <div className="top-avatar">TC</div>
          </div>
        </header>

        <div className="dashboard">
          <section className="welcome-row">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> MATCH INTELLIGENCE</div>
              <h1>{activeTab === "Overview" ? "Match overview" : activeTab === "Matches" ? "Matches" : activeTab === "Replay" ? "Pipeline replay" : "Player analysis"}<span>.</span></h1>
              <p className="page-subtitle">The details behind every moment on the pitch.</p>
            </div>
            <div className="source-controls">
              <label className="source-select-wrap">
                <span className="source-select-label">DATA SOURCE</span>
                <select aria-label="Data source" value={dataSource} onChange={(event) => changeSource(event.target.value as DataSource)}>
                  <option value="synthetic">Synthetic Demo</option>
                  <option value="statsbomb">Real Historical Matches · StatsBomb</option>
                  <option value="wyscout">Real Historical Matches · Wyscout</option>
                  <option value="results-archive">International Results ZIP</option>
                </select>
              </label>
              <div className={`data-badge ${dataSource !== "synthetic" ? "historical-badge" : ""}`}>
                <span>✳</span>
                {dataSource === "synthetic"
                  ? "Synthetic data · for demonstration"
                  : dataSource === "statsbomb" ? "StatsBomb Open Data · Historical"
                  : dataSource === "wyscout" ? "Wyscout Open Data · Historical"
                  : "User-provided results · Historical"}
              </div>
            </div>
          </section>

          {activeTab === "Replay" ? (
            <SimulationReplay />
          ) : activeTab === "Matches" ? (
            <MatchLibrary onOpenMatch={openCollectionMatch} onImportedMatch={openImportedMatch} />
          ) : !match ? (
            <section className="import-empty">
              <div className="empty-mark">◷</div>
              <h2>{loadingIndex || loadingMatch ? "Loading historical matches…" : "No imported historical matches"}</h2>
              <p>{dataSource === "statsbomb"
                ? "Import a match locally, then reload this list. Only the selected competition, season, match events, and lineups are downloaded."
                : dataSource === "wyscout"
                ? "Import a match locally, then reload this list. The importer downloads and caches only the selected competition's event segment."
                : "Import a match from your local ZIP, then reload this list. The archive stays on your computer."}</p>
              <code>{dataSource === "statsbomb"
                ? "python scripts/import_statsbomb.py"
                : dataSource === "wyscout"
                ? "python scripts/import_wyscout.py"
                : 'python scripts/import_results_archive.py "C:\\Users\\prana\\Downloads\\archive.zip"'}</code>
              <button className="reload-button" onClick={() => { historyCache.current.clear(); setReloadKey((key) => key + 1); }}>Reload imported matches</button>
              {historyError && <p className="history-error" role="alert">{historyError}</p>}
              <div className="attribution-note">
                {dataSource === "statsbomb"
                  ? <>Source: <a href="https://github.com/hudl/open-data" target="_blank" rel="noreferrer">StatsBomb Open Data</a>. Check README attribution and redistribution terms before publishing.</>
                  : dataSource === "wyscout"
                  ? <>Source: <a href="https://figshare.com/collections/Soccer_match_event_dataset/4415000" target="_blank" rel="noreferrer">Wyscout Soccer Match Event Dataset</a>, CC BY 4.0. Cite the data paper and retain attribution.</>
                  : <>Source: the selected local ZIP. Its original provenance and license were not included in the archive; do not redistribute without confirming permission.</>}
                {" "}Imported matches are historical and not live.
              </div>
              <button className="return-demo" onClick={() => changeSource("synthetic")}>Back to Synthetic Demo</button>
            </section>
          ) : (
            <>
              <section className="match-strip" aria-label="Selected match">
                <div className="match-detail">
                  <div className="match-label"><span className="calendar-icon">▦</span> {match.date}<span className="match-separator">·</span>{match.competition}</div>
                  <div className="scoreline">
                    <div className="club"><span className="club-crest" style={{ "--crest-color": match.homeColor } as React.CSSProperties}>{match.homeCode.slice(0, 1)}</span><strong>{match.homeTeam}</strong></div>
                    <div className="score">{homeScore}<span>:</span>{awayScore}</div>
                    <div className="club away"><strong>{match.awayTeam}</strong><span className="club-crest" style={{ "--crest-color": match.awayColor } as React.CSSProperties}>{match.awayCode.slice(0, 1)}</span></div>
                  </div>
                  <div className="venue"><span className={`venue-dot ${match.status === "historical" ? "historical-dot" : ""}`} />
                    {match.status === "historical" ? "HISTORICAL · NOT LIVE" : "FULL TIME"} <span>·</span> {match.venue}
                  </div>
                </div>
                <div className="match-tools">
                  <label className="select-wrap match-select-wrap">
                    <span className="sr-only">Select match</span>
                    <select value={matchId} onChange={(event) => { setMatchId(event.target.value); clearFilters(); }}>
                      {(dataSource === "synthetic" ? syntheticMatches : historicalMatches).map((item) => (
                        <option key={item.id} value={item.id}>{item.homeTeam} vs {item.awayTeam}</option>
                      ))}
                    </select>
                    <span className="select-chevron">⌄</span>
                  </label>
                  {dataSource !== "synthetic" && (
                    <button className="refresh-imports" onClick={() => { historyCache.current.clear(); setReloadKey((key) => key + 1); }}>Refresh imports</button>
                  )}
                    <div className="match-mini-stats">
                      <div><strong>{supportsMetric("shots") ? `${homeShots} — ${awayShots}` : "—"}</strong><small>SHOTS</small></div>
                      <div><strong>{supportsMetric("passes") ? matchAccuracy : "—"}</strong><small>PASS ACC.</small></div>
                  </div>
                </div>
              </section>

              {historyError && <div className="history-inline-error" role="alert">{historyError}</div>}
              {match.status === "historical" && match.dataQuality && (
                <section className="historical-notice">
                  <span className="notice-icon">ⓘ</span>
                  <div>
                    <strong>{match.source === "statsbomb-open-data"
                      ? "Historical StatsBomb data · not live"
                      : match.source === "wyscout-open-data"
                      ? "Historical Wyscout data · not live"
                      : "Historical results archive · not live"}</strong>
                    <span>
                      {match.source === "statsbomb-open-data"
                        ? <>Source: <a href={match.sourceUrl ?? "https://github.com/hudl/open-data"} target="_blank" rel="noreferrer">StatsBomb Open Data</a>. Score is calculated from logged goal events. Tackles count defensive duels labelled “Tackle”.</>
                        : match.source === "wyscout-open-data"
                        ? <>Source: <a href={match.sourceUrl ?? "https://figshare.com/collections/Soccer_match_event_dataset/4415000"} target="_blank" rel="noreferrer">Wyscout Soccer Match Event Dataset</a>, CC BY 4.0. Score and match statistics are calculated from logged events; tackles count Wyscout “Ground defending duel” events. This is historical data, not a live feed. Cite Pappalardo et al. (2019) and retain attribution when sharing.</>
                        : <>Source: user-provided ZIP (`results.csv` and `goalscorers.csv`). Final score comes from the archive's results row; scorer records are not a complete event log. The ZIP contains no provenance or license; verify permission before redistribution.</>}
                      {match.dataQuality.passEventsWithoutPassData > 0 && ` ${match.dataQuality.passEventsWithoutPassData} pass event(s) without pass data are excluded from accuracy.`}
                      {match.dataQuality.shotsWithoutOutcome > 0 && ` ${match.dataQuality.shotsWithoutOutcome} shot(s) without an outcome are excluded from shots on target.`}
                      {Object.keys(match.dataQuality.unrecognizedShotOutcomes ?? {}).length > 0 && ` Unrecognized shot outcomes (${Object.entries(match.dataQuality.unrecognizedShotOutcomes ?? {}).map(([name, count]) => `${name}: ${count}`).join(", ")}) are excluded from shots on target.`}
                      {match.dataQuality.missingPlayerEvents > 0 && ` ${match.dataQuality.missingPlayerEvents} event(s) have no player and cannot be assigned player statistics.`}
                      {match.dataQuality.missingTeamEvents > 0 && ` ${match.dataQuality.missingTeamEvents} event(s) have no team.`}
                      {match.dataQuality.missingSourceEventIds > 0 && ` ${match.dataQuality.missingSourceEventIds} event(s) had no source ID; generated replacement IDs are marked missing-id.`}
                      {(match.dataQuality.missingTimeEvents ?? 0) > 0 && ` ${match.dataQuality.missingTimeEvents} event(s) have no usable match time.`}
                      {(match.dataQuality.unresolvedLineupPlayers ?? 0) > 0 && ` ${match.dataQuality.unresolvedLineupPlayers} starting-lineup player ID(s) could not be resolved to a name.`}
                      {match.dataQuality.officialScoreMismatch && ` The event-derived score (${homeScore}-${awayScore}) differs from the repository's listed final score (${match.officialScore?.home ?? "?"}-${match.officialScore?.away ?? "?"}).`}
                      {match.dataQuality.scorerRecordMismatch && " The listed score does not match the available goal-scorer records; the listed score is authoritative."}
                      {match.source === "user-results-archive" && " Passing, shots, tackles, lineups, and other match events are not present and are shown as unavailable (not zero)."}
                      {(match.lineups?.length ?? 0) === 0 && " No lineup players were supplied; the table includes event participants only."}
                    </span>
                    {Object.keys(match.dataQuality.unsupportedEventTypes).length > 0 && (
                      <span>Other event types remain visible in the timeline but are not included in pass, shot, or tackle totals: {Object.entries(match.dataQuality.unsupportedEventTypes).map(([name, count]) => `${name} (${count})`).join(", ")}.</span>
                    )}
                    <span>Unsupported metrics: expected goals (xG) and possession percentages are not calculated.</span>
                  </div>
                </section>
              )}

              <section className="stats-grid" aria-label="Match statistics">
                <article className="stat-card score-card">
                  <div className="stat-top"><span className="stat-icon score-icon">◈</span><span className="stat-caption">MATCH RESULT</span><span className="stat-menu">···</span></div>
                  <div className="stat-value">{homeScore ?? "—"} <span>—</span> {awayScore ?? "—"}</div>
                  <div className="stat-foot"><span className="accent-dot" />
                    {homeScore === null || awayScore === null
                      ? "Result unavailable"
                      : homeScore === awayScore
                      ? match.status === "historical" ? "Level in recorded goals" : "Level at full time"
                      : `${homeScore > awayScore ? match.homeTeam : match.awayTeam} lead${match.status === "historical" ? " in recorded goals" : ""}`}
                  </div>
                </article>
                <article className="stat-card">
                  <div className="stat-top"><span className="stat-icon shot-icon">◎</span><span className="stat-caption">TOTAL SHOTS</span><span className="stat-menu">···</span></div>
                  <div className="stat-value">{supportsMetric("shots") ? totalShots.length : "—"}<span className="unit">{supportsMetric("shots") ? " shots" : ""}</span></div>
                  <div className="stat-foot split-foot">{supportsMetric("shots")
                    ? <><span>{match.homeCode} <b>{homeShots}</b></span><span>{match.awayCode} <b>{awayShots}</b></span></>
                    : <span>Not included in this archive</span>}</div>
                </article>
                <article className="stat-card">
                  <div className="stat-top"><span className="stat-icon target-icon">◎</span><span className="stat-caption">SHOTS ON TARGET</span><span className="stat-menu">···</span></div>
                  <div className="stat-value">{supportsMetric("shots") && knownShotsOnTarget.length ? shotsOnTarget : "—"}<span className="unit">{supportsMetric("shots") && knownShotsOnTarget.length ? ` / ${knownShotsOnTarget.length}` : ""}</span></div>
                  <div className="stat-foot">{!supportsMetric("shots") ? "Not included in this archive" : totalShots.length ? `${totalShots.length - knownShotsOnTarget.length} outcome(s) unavailable` : "No shot events"}</div>
                </article>
                <article className="stat-card">
                  <div className="stat-top"><span className="stat-icon pass-icon">⌁</span><span className="stat-caption">PASS ACCURACY</span><span className="stat-menu">···</span></div>
                  <div className="stat-value">{supportsMetric("passes") ? accuracyLabel(filteredEvents) : "—"}</div>
                  <div className="stat-foot"><span className="accent-dot blue-dot" />
                    {!supportsMetric("passes") ? "Not included in this archive" : team === "All teams" && !playerSearch ? `${matchAccuracy} across both teams` : "For current filters"}
                    {selectedPasses.length > knownSelectedPasses.length && ` · ${selectedPasses.length - knownSelectedPasses.length} missing`}
                  </div>
                </article>
              </section>

              <section className="analysis-grid">
                <article className="panel players-panel">
                  <div className="panel-heading">
                    <div><div className="section-kicker">SQUAD BREAKDOWN</div><h2>Player stats <span className="count-pill">{visibleStats.length}</span></h2></div>
                    <button className="text-button" onClick={() => setActiveTab("Players")}>View analysis <span>↗</span></button>
                  </div>
                  <div className="filters">
                    <label className="select-wrap team-select">
                      <span className="sr-only">Filter by team</span>
                      <span className="filter-prefix">TEAM</span>
                      <select value={team} onChange={(event) => setTeam(event.target.value)}>
                        <option>All teams</option>
                        {teams.map((teamName) => <option key={teamName}>{teamName}</option>)}
                      </select>
                      <span className="select-chevron">⌄</span>
                    </label>
                    <label className="search-wrap">
                      <span className="search-icon">⌕</span>
                      <input type="search" aria-label="Find player" placeholder="Find player..." value={playerSearch} onChange={(event) => setPlayerSearch(event.target.value)} />
                    </label>
                    {(team !== "All teams" || playerSearch) && <button className="clear-button" onClick={clearFilters}>Clear</button>}
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead><tr>
                        <th className="player-heading">PLAYER</th>
                        <th><button className="sort-button" disabled={!supportsMetric("passes")} onClick={() => selectSort("passes")}>PASSES <span>{supportsMetric("passes") ? sortKey === "passes" ? descending ? "↓" : "↑" : "↕" : "—"}</span></button></th>
                        <th><button className="sort-button" disabled={!supportsMetric("shots")} onClick={() => selectSort("shots")}>SHOTS <span>{supportsMetric("shots") ? sortKey === "shots" ? descending ? "↓" : "↑" : "↕" : "—"}</span></button></th>
                        <th><button className="sort-button" disabled={!supportsMetric("tackles")} onClick={() => selectSort("tackles")}>TACKLES <span>{supportsMetric("tackles") ? sortKey === "tackles" ? descending ? "↓" : "↑" : "↕" : "—"}</span></button></th>
                        <th><button className="sort-button" disabled={!supportsMetric("goals")} onClick={() => selectSort("goals")}>GOALS <span>{supportsMetric("goals") ? sortKey === "goals" ? descending ? "↓" : "↑" : "↕" : "—"}</span></button></th>
                      </tr></thead>
                      <tbody>
                        {visibleStats.map((stat) => {
                          const teamIndex = teams.indexOf(stat.team);
                          const crestColor = teamIndex === 0 ? match.homeColor : teamIndex === 1 ? match.awayColor : "#89919d";
                          const teamCode = teamIndex === 0 ? match.homeCode : teamIndex === 1 ? match.awayCode : "—";
                          return <tr key={`${stat.team}:${stat.name}`}>
                            <td><div className="player-cell"><span className="player-avatar" style={{ "--player-color": crestColor } as React.CSSProperties}>{stat.name.split(" ").map((part) => part[0]).join("")}</span><span className="player-identity"><strong>{stat.name}</strong><small><i style={{ background: crestColor }} />{teamCode}</small></span></div></td>
                            <td><span className="table-number">{supportsMetric("passes") ? stat.passes : "—"}</span>{supportsMetric("passes") && <span className="table-sub">{stat.completedPasses}/{stat.knownPasses} complete · {stat.missingPassData} unknown</span>}</td>
                            <td><span className="table-number">{supportsMetric("shots") ? stat.shots : "—"}</span></td>
                            <td><span className="table-number">{supportsMetric("tackles") ? stat.tackles : "—"}</span></td>
                            <td><span className="table-number">{supportsMetric("goals") ? stat.goals : "—"}</span></td>
                          </tr>;
                        })}
                        {visibleStats.length === 0 && <tr><td className="empty-state" colSpan={5}>No players match those filters.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                  <div className="table-footer"><span>Showing <b>{visibleStats.length}</b> of <b>{allStats.length}</b> players</span><span>Calculated from match events <span className="footer-spark">✳</span></span></div>
                </article>

                <article className="panel timeline-panel">
                  <div className="panel-heading timeline-heading">
                    <div><div className="section-kicker">IN-GAME MOMENTS</div><h2>Match timeline</h2></div>
                    <span className="event-count">{filteredEvents.length} EVENTS</span>
                  </div>
                  <div className="timeline-filter"><span>EVENT LOG</span><span className="filter-live"><i /> FILTERED EVENTS</span></div>
                  <div className="timeline-list">
                    {filteredEvents.length ? filteredEvents.map((event) => {
                      const isHome = event.team === match.homeTeam;
                      const teamCode = isHome ? match.homeCode : event.team === match.awayTeam ? match.awayCode : "—";
                      return <div className="timeline-event" key={event.eventId} title={`Source event ID: ${event.eventId}`}>
                        <div className="timeline-time">{event.minute}<small>'</small></div>
                        <div className="timeline-rail"><span className={`rail-dot ${event.type}`} /><span className="rail-line" /></div>
                        <EventMark type={event.type} />
                        <div className="event-copy"><strong>{getEventTitle(event)}</strong><span>{event.player || "Player unavailable"}</span></div>
                        <span className={`team-indicator ${isHome ? "home-indicator" : ""}`} title={event.team}>{teamCode}</span>
                      </div>;
                    }) : <div className="timeline-empty">No match events for this player.</div>}
                  </div>
                  <div className="timeline-footer"><span><i className="legend-dot goal-legend" /> Goal</span><span><i className="legend-dot shot-legend" /> Shot</span><span><i className="legend-dot pass-legend" /> Pass</span><span><i className="legend-dot tackle-legend" /> Tackle</span></div>
                </article>
              </section>
              <footer className="page-footer">
                <span>TACTICORE <b>·</b> LOCAL MATCH ANALYTICS</span>
                {match.status === "historical"
                  ? match.source === "statsbomb-open-data"
                    ? <span>Historical data from <a href={match.sourceUrl ?? "https://github.com/hudl/open-data"} target="_blank" rel="noreferrer">StatsBomb Open Data</a> · Not live</span>
                    : <span>User-provided international results archive · Historical · Not live</span>
                  : <span>All match data is synthetic and for demonstration only.</span>}
              </footer>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
