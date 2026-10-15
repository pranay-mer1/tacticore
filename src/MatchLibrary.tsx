import { useEffect, useMemo, useState } from "react";

export type MatchSource = "statsbomb-open-data" | "user-results-archive" | "wyscout-open-data";

export type CollectionMatch = {
  id: string;
  date: string;
  competition: string;
  homeTeam: string;
  awayTeam: string;
  file: string;
  cacheKey?: string;
  source: MatchSource;
};

type CatalogMatch = {
  matchId: number;
  date: string;
  competition: string;
  season: string;
  homeTeam: string;
  awayTeam: string;
  venue: string;
  imported: boolean;
};

type LibraryTab = "collection" | "browse";
type SortKey = "date" | "competition" | "homeTeam" | "awayTeam";

function isCollectionMatch(value: unknown): value is CollectionMatch {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" &&
    typeof item.date === "string" &&
    typeof item.competition === "string" &&
    typeof item.homeTeam === "string" &&
    typeof item.awayTeam === "string" &&
    typeof item.file === "string" &&
    (item.source === "statsbomb-open-data" ||
      item.source === "user-results-archive" ||
      item.source === "wyscout-open-data");
}

function isCatalogMatch(value: unknown): value is CatalogMatch {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.matchId === "number" && Number.isInteger(item.matchId) &&
    typeof item.date === "string" &&
    typeof item.competition === "string" &&
    typeof item.season === "string" &&
    typeof item.homeTeam === "string" &&
    typeof item.awayTeam === "string" &&
    typeof item.venue === "string" &&
    typeof item.imported === "boolean";
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const message = body && typeof body === "object" && typeof (body as Record<string, unknown>).error === "string"
      ? (body as Record<string, string>).error
      : `Request failed (HTTP ${response.status}).`;
    throw new Error(message);
  }
  return response.json();
}

function sourceName(source: MatchSource): string {
  if (source === "wyscout-open-data") return "Wyscout";
  if (source === "statsbomb-open-data") return "StatsBomb";
  return "Results ZIP";
}

function dateValue(value: string): string {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? "" : new Date(timestamp).toISOString().slice(0, 10);
}

type Props = {
  onOpenMatch: (match: CollectionMatch) => void;
  onImportedMatch: (matchId: string) => void;
};

export default function MatchLibrary({ onOpenMatch, onImportedMatch }: Props) {
  const [tab, setTab] = useState<LibraryTab>("collection");
  const [collection, setCollection] = useState<CollectionMatch[]>([]);
  const [catalog, setCatalog] = useState<CatalogMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [importingId, setImportingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [competitionFilter, setCompetitionFilter] = useState("All competitions");
  const [seasonFilter, setSeasonFilter] = useState("All seasons");
  const [teamFilter, setTeamFilter] = useState("All teams");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [descending, setDescending] = useState(true);
  const [page, setPage] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      fetch("/api/collection").then(readJson),
      fetch("/api/wyscout/catalog").then(readJson),
    ])
      .then(([collectionValue, catalogValue]) => {
        if (cancelled) return;
        if (!collectionValue || typeof collectionValue !== "object" ||
          !Array.isArray((collectionValue as { matches?: unknown }).matches) ||
          !catalogValue || typeof catalogValue !== "object" ||
          !Array.isArray((catalogValue as { matches?: unknown }).matches)) {
          throw new Error("The local match library returned an invalid response.");
        }
        const collectionRows = (collectionValue as { matches: unknown[] }).matches;
        const catalogRows = (catalogValue as { matches: unknown[] }).matches;
        if (!collectionRows.every(isCollectionMatch) || !catalogRows.every(isCatalogMatch)) {
          throw new Error("The local match library contains an invalid match record.");
        }
        setCollection(collectionRows);
        setCatalog(catalogRows);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load the local match library.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [reloadKey]);

  const sourceRows = tab === "browse" ? catalog : collection;
  const competitions = useMemo(
    () => [...new Set(sourceRows.map((row) => row.competition))].sort((a, b) => a.localeCompare(b)),
    [sourceRows],
  );
  const seasons = useMemo(
    () => tab === "browse" ? [...new Set(catalog.map((row) => row.season))].sort((a, b) => b.localeCompare(a)) : [],
    [catalog, tab],
  );
  const teams = useMemo(
    () => [...new Set(sourceRows.flatMap((row) => [row.homeTeam, row.awayTeam]))].sort((a, b) => a.localeCompare(b)),
    [sourceRows],
  );

  const visibleRows = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    const filtered = sourceRows.filter((row) => {
      const season = "season" in row ? row.season : "";
      const date = dateValue(row.date);
      return (competitionFilter === "All competitions" || row.competition === competitionFilter) &&
        (seasonFilter === "All seasons" || season === seasonFilter) &&
        (teamFilter === "All teams" || row.homeTeam === teamFilter || row.awayTeam === teamFilter) &&
        (!dateFrom || (!!date && date >= dateFrom)) &&
        (!dateTo || (!!date && date <= dateTo)) &&
        (!query || `${row.competition} ${season} ${row.homeTeam} ${row.awayTeam} ${row.date}`.toLocaleLowerCase().includes(query));
    });
    return filtered.sort((first, second) => {
      const comparison = (sortKey === "date"
        ? dateValue(first.date).localeCompare(dateValue(second.date))
        : first[sortKey].localeCompare(second[sortKey])) ||
        first.homeTeam.localeCompare(second.homeTeam) ||
        first.awayTeam.localeCompare(second.awayTeam);
      return descending ? -comparison : comparison;
    });
  }, [sourceRows, search, competitionFilter, seasonFilter, teamFilter, dateFrom, dateTo, sortKey, descending]);

  const pageSize = 50;
  const pageCount = Math.ceil(visibleRows.length / pageSize);
  const pageRows = visibleRows.slice(page * pageSize, (page + 1) * pageSize);

  const toggleSort = (key: SortKey) => {
    setPage(0);
    if (sortKey === key) setDescending((value) => !value);
    else {
      setSortKey(key);
      setDescending(key === "date");
    }
  };

  const changeFilter = (update: () => void) => {
    update();
    setPage(0);
  };

  const importMatch = async (matchId: number) => {
    setImportingId(matchId);
    setError("");
    try {
      const response = await fetch("/api/wyscout/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ matchId }),
      });
      const value = await readJson(response);
      const responseBody = value && typeof value === "object" ? value as Record<string, unknown> : null;
      const match = responseBody?.match && typeof responseBody.match === "object"
        ? responseBody.match as Record<string, unknown>
        : null;
      if (!match || typeof match.id !== "string") {
        throw new Error("The local importer returned an invalid match.");
      }
      const importedId = match.id;
      setReloadKey((current) => current + 1);
      setTab("collection");
      onImportedMatch(importedId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not import the selected match.");
    } finally {
      setImportingId(null);
    }
  };

  const clearFilters = () => {
    setSearch("");
    setCompetitionFilter("All competitions");
    setSeasonFilter("All seasons");
    setTeamFilter("All teams");
    setDateFrom("");
    setDateTo("");
    setPage(0);
  };

  return (
    <section className="match-library" aria-label="Match library">
      <header className="library-heading">
        <div>
          <div className="section-kicker">LOCAL MATCH LIBRARY</div>
          <h2>{tab === "collection" ? "Your collection" : "Browse historical matches"}</h2>
          <p>{tab === "collection"
            ? "Imported matches are saved on this computer and ready to analyze."
            : "Browse the Wyscout Open Data catalog and add selected historical matches."}</p>
        </div>
        <button className="reload-button" onClick={() => setReloadKey((current) => current + 1)} disabled={loading}>
          {loading ? "Loading…" : "Refresh library"}
        </button>
      </header>

      <div className="library-toolbar">
        <div className="library-tabs" role="tablist" aria-label="Match library view">
          <button role="tab" aria-selected={tab === "collection"} className={tab === "collection" ? "active" : ""}
            onClick={() => { setTab("collection"); clearFilters(); }}>
            My collection <span>{collection.length}</span>
          </button>
          <button role="tab" aria-selected={tab === "browse"} className={tab === "browse" ? "active" : ""}
            onClick={() => { setTab("browse"); clearFilters(); }}>
            Browse Wyscout
          </button>
        </div>
        <span className="library-history-label">HISTORICAL DATA · NOT LIVE</span>
      </div>

      {error && <div className="history-inline-error library-error" role="alert">
        {error}
        {(error.includes("Failed to fetch") || error.includes("NetworkError")) &&
          <span> Start <code>python scripts/local_api.py</code> in a second terminal, then refresh.</span>}
      </div>}

      <div className="library-filters">
        <label className="search-wrap"><span className="search-icon">⌕</span>
          <input type="search" placeholder="Search team, competition, date…" aria-label="Search matches" value={search}
            onChange={(event) => changeFilter(() => setSearch(event.target.value))} />
        </label>
        <label className="library-select"><span>COMPETITION</span>
          <select value={competitionFilter} onChange={(event) => changeFilter(() => setCompetitionFilter(event.target.value))}>
            <option>All competitions</option>
            {competitions.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        {tab === "browse" && <label className="library-select"><span>SEASON</span>
          <select value={seasonFilter} onChange={(event) => changeFilter(() => setSeasonFilter(event.target.value))}>
            <option>All seasons</option>
            {seasons.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>}
        <label className="library-select"><span>TEAM</span>
          <select value={teamFilter} onChange={(event) => changeFilter(() => setTeamFilter(event.target.value))}>
            <option>All teams</option>
            {teams.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <label className="date-filter"><span>FROM</span><input type="date" value={dateFrom}
          onChange={(event) => changeFilter(() => setDateFrom(event.target.value))} /></label>
        <label className="date-filter"><span>TO</span><input type="date" value={dateTo}
          onChange={(event) => changeFilter(() => setDateTo(event.target.value))} /></label>
        <button className="clear-button" onClick={clearFilters}>Clear filters</button>
      </div>

      <div className="library-table-scroll">
        <table className="library-table">
          <thead><tr>
            <th><button className="sort-button" onClick={() => toggleSort("date")}>DATE{sortKey === "date" && <span>{descending ? " ↓" : " ↑"}</span>}</button></th>
            <th><button className="sort-button" onClick={() => toggleSort("competition")}>COMPETITION{sortKey === "competition" && <span>{descending ? " ↓" : " ↑"}</span>}</button></th>
            {tab === "browse" && <th>SEASON</th>}
            <th><button className="sort-button" onClick={() => toggleSort("homeTeam")}>HOME TEAM{sortKey === "homeTeam" && <span>{descending ? " ↓" : " ↑"}</span>}</button></th>
            <th><button className="sort-button" onClick={() => toggleSort("awayTeam")}>AWAY TEAM{sortKey === "awayTeam" && <span>{descending ? " ↓" : " ↑"}</span>}</button></th>
            <th>{tab === "browse" ? "SOURCE" : "DATA SOURCE"}</th>
            <th>{tab === "browse" ? "ACTION" : "OPEN"}</th>
          </tr></thead>
          <tbody>
            {pageRows.map((row) => {
              if (tab === "browse") {
                const item = row as CatalogMatch;
                return <tr key={item.matchId}>
                  <td>{item.date || "Date unavailable"}</td>
                  <td>{item.competition}</td>
                  <td>{item.season}</td>
                  <td>{item.homeTeam}</td>
                  <td>{item.awayTeam}</td>
                  <td><span className="source-pill wyscout-pill">Wyscout · Historical</span></td>
                  <td>{item.imported
                    ? <span className="saved-label">In collection</span>
                    : <button className="add-match-button" onClick={() => void importMatch(item.matchId)}
                      disabled={importingId !== null}>{importingId === item.matchId ? "Importing…" : "Add to collection"}</button>}</td>
                </tr>;
              }
              const item = row as CollectionMatch;
              return <tr key={item.id}>
                <td>{item.date}</td>
                <td>{item.competition}</td>
                <td>{item.homeTeam}</td>
                <td>{item.awayTeam}</td>
                <td><span className="source-pill">{sourceName(item.source)} · Historical</span></td>
                <td><button className="add-match-button" onClick={() => onOpenMatch(item)}>Open analysis</button></td>
              </tr>;
            })}
            {!loading && pageRows.length === 0 && <tr><td colSpan={tab === "browse" ? 7 : 6} className="library-empty">
              {error ? "The local match library could not be loaded." : "No matches found. Try another filter or browse the catalog."}
            </td></tr>}
          </tbody>
        </table>
      </div>
      <footer className="library-footer">
        <span>{visibleRows.length.toLocaleString()} matches · {tab === "collection" ? "saved locally" : "available in the Wyscout historical sample"}</span>
        <div>
          <button className="pagination-button" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>Previous</button>
          <span>Page {pageCount === 0 ? 0 : page + 1} of {pageCount}</span>
          <button className="pagination-button" disabled={page + 1 >= pageCount} onClick={() => setPage((current) => current + 1)}>Next</button>
        </div>
      </footer>
      <p className="library-attribution">
        Historical, not live. Wyscout data: <a href="https://figshare.com/collections/Soccer_match_event_dataset/4415000" target="_blank" rel="noreferrer">Soccer Match Event Dataset</a>, CC BY 4.0. Retain attribution and licence details when redistributing.
      </p>
    </section>
  );
}
