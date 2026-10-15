export type EventType = "pass" | "shot" | "tackle" | "goal" | "other";
export type MatchSource = "synthetic" | "statsbomb-open-data" | "user-results-archive" | "wyscout-open-data";
export type MatchMetric = "goals" | "passes" | "shots" | "tackles";

export type FootballEvent = {
  eventId: string;
  minute: number;
  second?: number;
  team: string;
  player: string;
  type: EventType;
  completed?: boolean | null;
  passOutcome?: string | null;
  outcome?: string | null;
  onTarget?: boolean | null;
  successful?: boolean | null;
  goalOwnGoal?: boolean;
  goalPenalty?: boolean;
  goalTeam?: string;
  sourceEventType?: string;
  sourceEventName?: string;
};

export type FootballMatch = {
  id: string;
  sourceMatchId?: number;
  date: string;
  competition: string;
  venue: string;
  homeTeam: string;
  awayTeam: string;
  homeCode: string;
  awayCode: string;
  homeColor: string;
  awayColor: string;
  source: MatchSource;
  status: "synthetic" | "historical";
  availableMetrics?: MatchMetric[];
  sourceUrl?: string;
  officialScore?: {
    home: number | null;
    away: number | null;
  };
  lineups?: Array<{
    team: string;
    players: string[];
  }>;
  dataQuality?: {
    missingPlayerEvents: number;
    missingTeamEvents: number;
    missingSourceEventIds: number;
    passEventsWithoutPassData: number;
    shotsWithoutOutcome: number;
    missingTimeEvents?: number;
    unresolvedLineupPlayers?: number;
    unrecognizedShotOutcomes: Record<string, number>;
    unsupportedEventTypes: Record<string, number>;
    unavailableMetrics: string[];
    officialScoreMismatch?: boolean;
    scorerRecordMismatch?: boolean;
    scorerRecords?: number;
  };
  events: FootballEvent[];
};
