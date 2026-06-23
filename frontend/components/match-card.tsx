import type { Match } from "@/types";

function isLive(status: string) {
  return ["LIVE", "1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"].includes(status);
}

function formatKickoff(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZoneName: "short"
  }).format(new Date(value));
}

function formatStatus(match: Match) {
  if (match.status === "SUSP") return match.minute ? `${match.minute}' DELAYED` : "MATCH DELAYED";
  if (isLive(match.status)) return match.minute ? `${match.minute}' LIVE` : "LIVE";
  if (["FT", "AET", "PEN"].includes(match.status)) return "FINAL";
  if (match.status === "PST") return "POSTPONED";
  if (match.status === "CANC") return "CANCELLED";
  return formatKickoff(match.kickoff_at);
}

export function MatchCard({ match, onOpen }: { match: Match; onOpen: (match: Match) => void }) {
  const live = isLive(match.status);
  const hasScore = match.home_score !== null && match.away_score !== null;
  const historical = match.provider_id.startsWith("statsbomb:");

  return (
    <article className={`match-card ${live ? "match-card-live" : ""}`}>
      <header className="match-header">
        <span>{match.stage}</span>
        <span className={live ? "live-label" : ""}>{formatStatus(match)}</span>
      </header>

      <div className="teams">
        <div className="team-row">
          <div className="team-name"><span className="team-code">{match.home_team.code ?? "—"}</span>{match.home_team.name}</div>
          <strong>{hasScore ? match.home_score : "–"}</strong>
        </div>
        <div className="team-row">
          <div className="team-name"><span className="team-code">{match.away_team.code ?? "—"}</span>{match.away_team.name}</div>
          <strong>{hasScore ? match.away_score : "–"}</strong>
        </div>
      </div>

      <div className="prediction-block">
        <div className="prediction-labels">
          <span>{match.home_team.code ?? match.home_team.name} <strong>{match.prediction.home_win.toFixed(0)}%</strong></span>
          <span>Draw <strong>{match.prediction.draw.toFixed(0)}%</strong></span>
          <span><strong>{match.prediction.away_win.toFixed(0)}%</strong> {match.away_team.code ?? match.away_team.name}</span>
        </div>
        <div className="probability-bar" aria-label="Match prediction probabilities">
          <span className="home-probability" style={{ width: `${match.prediction.home_win}%` }} />
          <span className="draw-probability" style={{ width: `${match.prediction.draw}%` }} />
          <span className="away-probability" style={{ width: `${match.prediction.away_win}%` }} />
        </div>
      </div>

      <p className="prediction-explainer">{match.prediction.summary}</p>
      <footer className="match-footer">
        <span>{match.venue ?? "Venue to be confirmed"}</span>
        <button className="match-center-button" type="button" onClick={() => onOpen(match)}>
          {historical ? "Player stats & rating →" : "Open match center →"}
        </button>
      </footer>
    </article>
  );
}
