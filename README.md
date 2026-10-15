<div align="center">

# Tacticore

**Football intelligence. Explained.**

A local-first football analytics dashboard built with **React**, **TypeScript**, and **Vite**.

Synthetic match replay · Historical match analysis · Player insights · Optional Microsoft Foundry explanations

</div>

---

## Overview

Tacticore brings match events, player statistics, tactical patterns, and evidence-linked explanations into one dashboard.

> **Data coverage:** Synthetic Demo is available for demonstrations. Imported matches are historical—not live feeds.

| Mode | Data | Best for |
| --- | --- | --- |
| **Synthetic Demo / Pipeline replay** | Repeatable generated match events | Demonstrations and the five-stage pipeline |
| **StatsBomb Open Data** | Historical events and lineups | Match and player analysis |
| **Wyscout public dataset** | Historical events and match metadata | Browsing, collecting and analysing matches |
| **International Results ZIP** | Results and goalscorers | Scores and goal timelines |

**Microsoft Foundry is optional.** Local statistics and deterministic insights work without AI configuration.

## Contents

- [Quick start](#quick-start)
- [Match library](#match-library)
- [Synthetic pipeline](#synthetic-pipeline)
- [Import historical matches](#import-historical-matches)
- [International results archive](#international-results-archive)
- [Wyscout imports](#wyscout-imports)
- [Wyscout interpretation and attribution](#wyscout-data-interpretation-and-attribution)
- [Data interpretation](#data-interpretation)
- [Source attribution](#source-attribution)
- [Build and checks](#build-and-checks)

## Requirements

- Node.js 20.19+ or 22.12+ (npm is included with Node.js)
- Python 3.10+
- Deno 2 (optional, for the TypeScript simulation invariant tests)
- Internet access for source downloads and optional Foundry explanations; the dashboard reads local match files

## Quick start

From the project folder, install frontend dependencies:

```bash
npm install
```

Start the frontend in one terminal:

```bash
npm run dev
```

Start the local match API in a second terminal:

```bash
npm run dev:api
```

Open the local URL printed by Vite, normally **http://localhost:5173/**, in a browser. Keep both terminals running while using the match library. Press `Ctrl+C` in each terminal to stop its server.

The dashboard and synthetic demo work without the API; match browsing and website imports need it.

## Match library

1. Start both `npm run dev` and `npm run dev:api` as described above.

2. Open **Matches** in the left navigation, then select **Browse Wyscout**.

3. Filter by competition, season, team, date range, or search text. Click the column headings to sort by date, competition, home team, or away team.

4. Select **Add to collection** beside a match. Tacticore downloads only that competition's event segment (using the existing range-download and local-cache behavior), converts the selected match, and saves it under `public/data/historical/`.

5. Find saved games in **My collection**. Sort and filter the same way, then choose **Open analysis** to load that match in the dashboard. Imported matches are also available in the existing data-source and match selectors.

The first catalog visit downloads and caches Wyscout's small competition/team/match metadata files. Later visits read the local cache; match event data is requested only when you add a match, and cached event segments are reused. The collection is the existing local historical-match index, so it also includes StatsBomb and user-provided results imports. Nothing is uploaded to a Tacticore server.

## Synthetic pipeline

Open **Pipeline replay** in the left navigation. It is a separate, clearly labelled **synthetic match simulation**; it does not change the selected historical-data source or its match files.

### Available locally

| Stage | What Tacticore does |
| --- | --- |
| **1 · Ingest** | Generates seeded, repeatable lineups, metadata, passes, shots, tackles, pressure events, possession changes and substitutions. |
| **2 · Interpret** | Calculates score, pass completion, player action counts, attacking shot zones, defensive-third turnovers and pressure comparisons from received events. |
| **3 · Explain** | Produces deterministic insight cards that separate recorded observations from tentative tactical hypotheses. Cards remain available when AI is unconfigured or unavailable. |
| **4 · Render** | Synchronizes a 2D pitch, timeline, current-player highlight, insight cards and event-linked half-time/full-time recaps. |
| **5 · Personalize** | Supports Analyst/Fan modes, English/Spanish, favourite teams and followed players. Preferences are saved in the browser; filters constrain statistics and insight evidence. |

**Replay controls:** play, pause, step, speed, seek, reset and new seed. Only events reached by the replay clock are streamed.

**Evidence thresholds:** defensive-turnover patterns require three linked sequences in a rolling 10-minute window. Pressure comparisons require evidence in both adjacent 10-minute windows. Insights include supporting event IDs and expire with match time.

> Simulated pitch coordinates are illustrative; they are not player-tracking measurements.

**Validation:** `npm run test:simulation` checks deterministic generation, event-derived statistics, progressive evidence with no future event IDs, and filter-aware patterns.

### Optional Microsoft Foundry explanations

The local Python backend exposes `POST /api/foundry/explain`. To enable it, configure an Azure AI Foundry chat-completions deployment, then set these variables in the same PowerShell terminal used to start the API (never commit the key):

```powershell
$env:AZURE_AI_FOUNDRY_ENDPOINT = "https://<your-resource>.services.ai.azure.com/models"
$env:AZURE_AI_FOUNDRY_API_KEY = "<your-api-key>"
$env:AZURE_AI_FOUNDRY_MODEL = "<your-deployment-name>"
python scripts/local_api.py
```

Restart the API after changing configuration. Without all three values, replay analysis works locally and the Foundry explanation control stays unavailable.

For an explanation request, the browser sends only the currently received, filtered statistics and supporting events; the backend rejects evidence later than the replay time and rejects numeric claims absent from that request. Model output is still fallible: AI text is supplementary to the deterministic observation and evidence, not a substitute for verification.

The replay defaults to a fixed seed for repeatable demonstrations. **Reset** returns to event zero and clears the visible replay state; **New simulation** selects a different seed. Structured insights and AI explanations are cached locally by deterministic insight ID so the same replay can reuse them.

## Import historical matches

1. Leave the Vite development server running (or start it with `npm run dev`).

2. Open a second terminal in the project folder.

3. Run:

   ```bash
   python scripts/import_statsbomb.py
   ```

   Or, if you prefer npm scripts, run `npm run import:statsbomb`.

4. In the importer, choose a competition, then a season, then one match. It downloads only `competitions.json`, the selected competition/season match list, and that match's event and lineup files. The source files are cached locally.

5. Return to the browser. In **Data source**, choose **Real Historical Matches · StatsBomb**, then click **Reload imported matches** (or **Refresh imports**) to load the new match. Choose it in the match selector; its player table, filters, statistics, and event timeline use the imported data.

## International results archive

The optional `archive.zip` contains `results.csv`, `goalscorers.csv`, `shootouts.csv`, and `former_names.csv`. This is a different, score-and-scorer dataset—not StatsBomb event data. It has no passes, shots, tackles, lineups, or full match-event stream. Tacticore uses the results row for the final score and scorer rows for the goal timeline and scorer table; unavailable metrics display `—`, not zero. From a second terminal, point the importer at your ZIP:

```bash
python scripts/import_results_archive.py "C:\path\to\archive.zip"
```

Or run `npm run import:results-archive -- "C:\path\to\archive.zip"`. Choose a tournament, year, and match. In the dashboard, choose **International Results ZIP**, click **Reload imported matches**, and select your match. Keep the ZIP on your computer; imported match JSON is written to the same local historical-match directory as StatsBomb imports. Use **Real Historical Matches · StatsBomb** for matches with event-level passes, shots, tackles, and lineups. If your local setup includes the imported Argentina–France 2022 World Cup final, find it under **International Results ZIP** after refreshing the imports.

The supplied ZIP contains no README, license, or source attribution, so its upstream provenance and redistribution permission are unverified. This importer labels it as a user-provided archive and does not republish the ZIP itself. Do not distribute the archive or derived match data until you have verified the original source and license.

## Wyscout imports

1. Leave the Vite development server running.

2. In a second terminal in the project folder, run:

   ```bash
   python scripts/import_wyscout.py
   ```

   Or run `npm run import:wyscout`.

3. Choose a competition, season, and match from the prompts to import one match.

4. To import the entire published Wyscout match catalog in one batch instead, run:

   ```bash
   python scripts/import_wyscout.py --all
   ```

   Or use `npm run import:wyscout:all`. The batch imports every played match in all supported competitions and seasons, reports progress, skips matches already cached locally, and adds imported games to the same website collection. To batch only one competition or season, use `--all --competition "English first division"` or `--all --season "2017/18"`; both filters can be combined.

5. In Tacticore, open **Matches → My collection** or choose **Real Historical Matches · Wyscout** to analyze the imported games.

The importer downloads small competition/match/team/player metadata files, then uses HTTP byte ranges to fetch and cache only the competition event segments needed for your import. It refuses to continue if the source server does not honor range requests. A single-match import fetches only that match's competition segment; `--all` fetches the segments for all supported competitions. Segments are cached in `.cache/wyscout/events/`; imported, normalized match JSON is written under `public/data/historical/matches/`. Re-running a batch skips matches already imported and reuses cached segments. Use `--refresh` only when you explicitly want to refresh source caches and re-import.

The public sample covers English, French, German, Italian, and Spanish first divisions, the 2016 European Championship, and the 2018 World Cup. These are historical seasons, not current-season or live coverage. The importer derives season labels from the match dates. Wyscout is not live because this public Figshare collection is a fixed historical release, not a continuously updated match feed. Current or live matches require a separate provider with current coverage and typically a paid/licensed API.

## Wyscout data interpretation and attribution

The [Wyscout Soccer Match Event Dataset](https://figshare.com/collections/Soccer_match_event_dataset/4415000) is published on Figshare under **CC BY 4.0**. Its event records provide event IDs, player/team IDs, time, positions, and event tags. Tacticore preserves each source event's original numeric ID as a string in `eventId`, and records the Wyscout source on the match.

- Passes and passing accuracy use the source's **Accurate** and **Not accurate** tags. Passes without either tag count as passes, but are excluded from the accuracy denominator.
- Shots are source `Shot` events. A source **Goal** tag sets the goal outcome; on-target status is inferred from the documented goal-position tags, while blocked, out, and post-position tags are off target. Shots without a recognized tag remain unknown, not guessed.
- Tackles use Wyscout **Ground defending duel** events. This is the dataset's event-taxonomy measure, not a separately supplied official tackle statistic.
- Own goals are credited to the opposing team's event-derived score; they are not credited as a scorer's personal goals. The displayed score is calculated from events, and the source match score is retained to flag discrepancies.
- Other source event types remain in the timeline but are not counted as passes, shots, or tackles. xG and possession are not supplied or calculated. Unknown player/team IDs and missing event times are reported in the match notice.

When sharing or redistributing data or analysis, comply with the [CC BY 4.0 licence](https://creativecommons.org/licenses/by/4.0/): provide appropriate attribution, link the licence, and indicate modifications. Cite Pappalardo, Cintia, Rossi et al., *A public data set of spatio-temporal match events in soccer competitions*, *Scientific Data* 6, 236 (2019), [doi:10.1038/s41597-019-0247-7](https://doi.org/10.1038/s41597-019-0247-7), and the [Figshare Events dataset](https://doi.org/10.6084/m9.figshare.7770599.v1). This app links to the source and labels imported matches as historical; retain that attribution and licensing information in any permitted redistribution.

Imported dashboard files are stored under `public/data/historical/`; download caches are in `.cache/statsbomb/` and `.cache/wyscout/`.

Re-running an importer uses its caches rather than requesting the same source files again. Imported match JSON and caches are local files and are not committed to source control by default.

If the app was already open and does not show a new import, select **Reload imported matches**. If you create `public/` for the first time after starting Vite and the files are not served, restart Vite and reload the imports.

## Data interpretation

- StatsBomb scores are calculated from logged goal events. The results ZIP's score comes from its `results.csv` row; its goal-scorer records are not a complete event log and are checked against that score.
- Passing accuracy is completed passes divided by passes with a known completion result. StatsBomb's omitted pass outcome indicates a completed pass; an event without a pass payload has an unknown result and is excluded from the accuracy denominator.
- Shots on target include shot outcomes `Goal`, `Saved`, and `Saved to Post`; known off-target outcomes include `Off T`, `Wayward`, `Post`, `Blocked`, and `Saved Off Target`. Missing or unrecognized shot outcomes are not guessed and are excluded from the shots-on-target count, with data-quality notes shown in the dashboard.
- Tackles count StatsBomb `Duel` events whose subtype is `Tackle`. Other duels are not silently counted as tackles.
- Wyscout passes use accuracy tags, and Wyscout tackles count `Ground defending duel` events; see the source-specific interpretation above.
- Other event types and original event IDs remain in the match timeline. Unsupported event types are listed in the match's data-quality notice and excluded from pass/shot/tackle totals.
- Players listed in the imported lineups are included in the table even if they have no recorded event. Events with no player name remain visible, but cannot be assigned player statistics.
- Expected goals (xG) and possession percentages are not calculated.

## Source attribution

### StatsBomb Open Data

Source: [StatsBomb Open Data](https://github.com/hudl/open-data). Its [README terms](https://github.com/hudl/open-data#terms--conditions) describe the data as freely available for research and genuine interest in football analytics. They require that published, shared, or distributed research, analysis, or insights based on the data state **StatsBomb** as the source and use the official StatsBomb logo from its [Media Pack](https://statsbomb.com/media-pack/).

The repository README is a terms notice, not a blanket license to redistribute the raw dataset or imported match files.

This app imports and caches files for local use; before publishing or redistributing raw data, derived datasets, or analysis, check the current repository terms and obtain any additional permission that is required. Keep the attribution with any permitted publication.

The historical-data view links to the source; it does not embed the StatsBomb logo.

### User-provided results archive

The ZIP does not contain metadata identifying its creator or original source, and no license is included. The app therefore attributes it only as a **user-provided international results archive**, not to an assumed upstream project. Verify the source and license independently before sharing, publishing, or redistributing any of its contents or derived results.

## Build and checks

```bash
npm run build
npm run test:importer
```

Run the simulation invariant tests with Deno 2 installed:

```bash
npm run test:simulation
```

To preview the production build locally:

```bash
npm run preview
```
