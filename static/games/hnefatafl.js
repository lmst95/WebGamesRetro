const hnefataflView = document.getElementById("hnefataflView");
const hnefataflBoard = document.getElementById("hnefataflBoard");
const activePlayer = document.getElementById("activePlayer");
const moveForm = document.getElementById("moveForm");
const moveLog = document.getElementById("moveLog");
const gameModal = document.getElementById("gameModal");
const modalTitle = document.getElementById("modalTitle");
const modalBody = document.getElementById("modalBody");
const newGameBtn = document.getElementById("newGameBtn");
const statsLine = document.getElementById("statsLine");
const timeLine = document.getElementById("timeLine");
const seatLine = document.getElementById("seatLine");
const roleLine = document.getElementById("roleLine");
const fromField = document.getElementById("fromField");
const toField = document.getElementById("toField");
const submitBtn = moveForm ? moveForm.querySelector("button[type='submit']") : null;

const initialBoard = [
  "...AAA...",
  "....A....",
  "....D....",
  "A...D...A",
  "AADDKDDAA",
  "A...D...A",
  "....D....",
  "....A....",
  "...AAA...",
];

const files = ["a", "b", "c", "d", "e", "f", "g", "h", "i"];
let boardState = initialBoard.map((row) => row.split(""));
let currentPlayer = 1;
let viewPlayer = hnefataflView ? Number(hnefataflView.dataset.player || 0) : 0;
let gameMode = hnefataflView ? hnefataflView.dataset.game || "public" : "public";
let seatPlayer = 0;
const moveHistory = [];
let gameOver = false;
let lastVersion = null;
let lastResult = null;
let pollTimer = null;
let timeTimer = null;
let timeBase = null;

function applySeatTheme() {
  if (!hnefataflView) {
    return;
  }
  hnefataflView.classList.toggle("is-seat-2", gameMode === "seats" && seatPlayer === 2);
}

if (moveForm) {
  moveForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (gameOver || !fromField || !toField) {
      return;
    }

    const from = fromField.value.trim().toLowerCase();
    const to = toField.value.trim().toLowerCase();
    const coordPattern = /^[a-i][1-9]$/;
    if (!coordPattern.test(from) || !coordPattern.test(to)) {
      return;
    }

    submitMove(from, to);
  });
}

if (newGameBtn) {
  newGameBtn.addEventListener("click", () => {
    requestReset();
  });
}

function pieceMarkup(piece) {
  if (piece === ".") {
    return " ";
  }
  const isP1 = piece === "K" || piece === "D";
  const pieceClass = isP1 ? "piece piece-p1" : "piece piece-p2";
  return `<span class="${pieceClass}">${piece}</span>`;
}

function shakeSubmitButton() {
  if (!submitBtn) {
    return;
  }
  submitBtn.classList.remove("is-shake");
  void submitBtn.offsetWidth;
  submitBtn.classList.add("is-shake");
}

function renderBoard(player) {
  const rows = boardState.map((row) => [...row]);
  const rankLabels = player === 2 ? [1, 2, 3, 4, 5, 6, 7, 8, 9] : [9, 8, 7, 6, 5, 4, 3, 2, 1];
  const fileLabels = player === 2 ? [...files].reverse() : files;

  if (player === 2) {
    rows.reverse();
    rows.forEach((row) => row.reverse());
  }

  const lines = [];
  lines.push("    " + fileLabels.map((f) => ` ${f} `).join(" "));
  lines.push("   +" + "---+".repeat(9));

  rows.forEach((row, index) => {
    const rank = rankLabels[index];
    const cells = row.map((piece, fileIndex) => {
      const symbol = pieceMarkup(piece);
      const shade = (index + fileIndex) % 2 === 0 ? " " : "#";
      return `${shade}${symbol}${shade}`;
    });
    const rankLabel = String(rank).padStart(2, " ");
    lines.push(`${rankLabel} |${cells.join("|")}|`);
    lines.push("   +" + "---+".repeat(9));
  });

  lines.push("    " + fileLabels.map((f) => ` ${f} `).join(" "));
  hnefataflBoard.innerHTML = lines.join("\n");
}

function getGameQuery() {
  return gameMode === "seats" ? "seats" : "public";
}

function buildStateUrl() {
  const game = getGameQuery();
  return `/hnefatafl/state?game=${game}`;
}

async function fetchState() {
  try {
    const response = await fetch(buildStateUrl(), { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (lastVersion !== data.version) {
      lastVersion = data.version;
      applyState(data);
    }
  } catch (error) {
    console.warn("Failed to fetch state", error);
  }
}

function applyState(state) {
  boardState = state.board.map((row) => row.split(""));
  currentPlayer = state.current_player;
  moveHistory.length = 0;
  moveHistory.push(...state.move_history);
  gameOver = state.game_over;
  lastResult = state.result || null;
  if (gameMode === "seats" && state.seat_info) {
    seatPlayer = state.seat_info.player || 0;
    viewPlayer = seatPlayer || 0;
    if (seatLine) {
      const p1 = state.seat_info.p1 ? "taken" : "open";
      const p2 = state.seat_info.p2 ? "taken" : "open";
      seatLine.textContent = `seat://p1 ${p1} | p2 ${p2}`;
    }
    if (roleLine) {
      if (seatPlayer === 1) {
        roleLine.textContent = "role://seat 1 (defenders)";
      } else if (seatPlayer === 2) {
        roleLine.textContent = "role://seat 2 (attackers)";
      } else {
        roleLine.textContent = "role://visitor";
      }
    }
  } else if (seatLine) {
    seatLine.textContent = "seat://p1 open | p2 open";
    if (roleLine) {
      roleLine.textContent = "role://public";
    }
  }
  applySeatTheme();
  if (activePlayer) {
    activePlayer.textContent = String(currentPlayer);
  }
  if (statsLine && state.stats) {
    const p1Wins = Number(state.stats.p1_wins || 0);
    const p2Wins = Number(state.stats.p2_wins || 0);
    const draws = Number(state.stats.draws || 0);
    const totalGames = Number(state.stats.total_games || 0);
    statsLine.textContent = `stats://p1 ${p1Wins} wins | p2 ${p2Wins} wins | draws ${draws} | games ${totalGames}`;
  }
  if (state.server_time) {
    timeBase = {
      startedAt: state.started_at ?? null,
      lastPlayedAt: state.last_played_at ?? null,
      serverTime: state.server_time,
      clientTime: Date.now() / 1000,
      frozenAt: state.game_over ? (state.last_played_at ?? state.server_time) : null,
    };
  }
  renderBoard(viewPlayer);
  renderMoveLog();
  updateInputAvailability();
  updateTimeLine();
  if (gameOver && lastResult) {
    showGameOver(formatGameOver(lastResult));
  } else if (gameModal) {
    gameModal.classList.remove("open");
    gameModal.setAttribute("aria-hidden", "true");
  }
}

function formatGameOver(result) {
  if (!result || result.winner == null) {
    return result;
  }
  if (![1, 2].includes(viewPlayer)) {
    return result;
  }
  if (viewPlayer === result.winner) {
    return { title: "Victory", message: "You win" };
  }
  return { title: "Defeat", message: "You lose" };
}

function formatDuration(totalSeconds) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function updateTimeLine() {
  if (!timeLine) {
    return;
  }
  if (!timeBase) {
    timeLine.textContent = "time://last --:-- | game --:--";
    return;
  }
  const nowClient = Date.now() / 1000;
  const liveNow = timeBase.serverTime + (nowClient - timeBase.clientTime);
  const serverNow = timeBase.frozenAt ?? liveNow;
  const lastPlayed = timeBase.lastPlayedAt ? formatDuration(serverNow - timeBase.lastPlayedAt) : "--:--";
  const gameDuration = timeBase.startedAt ? formatDuration(serverNow - timeBase.startedAt) : "--:--";
  const lastLabel = timeBase.frozenAt ? "ended" : `last ${lastPlayed}`;
  timeLine.textContent = `time://${lastLabel} | game ${gameDuration}`;
}

async function submitMove(from, to) {
  try {
    if (gameMode === "seats" && seatPlayer === 0) {
      return;
    }
    const response = await fetch(`/hnefatafl/move?game=${getGameQuery()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player: viewPlayer,
        from,
        to,
      }),
    });
    if (!response.ok) {
      shakeSubmitButton();
      return;
    }
    const data = await response.json();
    if (!data.ok) {
      shakeSubmitButton();
      return;
    }
    if (data.state) {
      lastVersion = data.state.version;
      applyState(data.state);
    }
    if (fromField) {
      fromField.value = "";
    }
    if (toField) {
      toField.value = "";
    }
  } catch (error) {
    console.warn("Failed to submit move", error);
  }
}

async function requestReset() {
  try {
    if (gameMode === "seats" && seatPlayer === 0) {
      return;
    }
    const response = await fetch(`/hnefatafl/reset?game=${getGameQuery()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player: viewPlayer,
      }),
    });
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (data.state) {
      lastVersion = data.state.version;
      applyState(data.state);
    }
  } catch (error) {
    console.warn("Failed to reset game", error);
  }
}

async function claimSeat() {
  try {
    const response = await fetch("/hnefatafl/seat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (!data.ok) {
      return;
    }
    seatPlayer = data.player || 0;
    viewPlayer = seatPlayer || 0;
    applySeatTheme();
    if (data.state) {
      lastVersion = data.state.version;
      applyState(data.state);
    }
  } catch (error) {
    console.warn("Failed to claim seat", error);
  }
}

function startPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
  }
  pollTimer = setInterval(() => {
    fetchState();
  }, 1500);
  if (gameMode === "seats") {
    claimSeat();
  } else {
    fetchState();
  }
  if (!timeTimer) {
    timeTimer = setInterval(updateTimeLine, 1000);
  }
}

function updateInputAvailability() {
  if (!moveForm) {
    return;
  }
  const isSpectator = gameMode === "seats" && seatPlayer === 0;
  const isActiveView = viewPlayer === currentPlayer && !gameOver && !isSpectator;
  let statusText = "Waiting for other player";
  if (isSpectator) {
    statusText = "Spectator mode";
  } else if (gameMode === "seats" && seatPlayer > 0 && seatPlayer !== currentPlayer) {
    statusText = "Waiting for your turn";
  } else if (gameOver) {
    statusText = "Game over";
  }
  moveForm.dataset.status = statusText;
  moveForm.classList.toggle("is-disabled", !isActiveView);
  [fromField, toField, submitBtn].forEach((el) => {
    if (!el) {
      return;
    }
    el.disabled = !isActiveView;
  });
  moveForm.setAttribute("aria-disabled", isActiveView ? "false" : "true");
}

function showGameOver(result) {
  if (!gameModal || !modalTitle || !modalBody) {
    return;
  }
  modalTitle.textContent = result.title;
  modalBody.textContent = result.message;
  gameModal.classList.add("open");
  gameModal.setAttribute("aria-hidden", "false");
  gameOver = true;
}

function renderMoveLog() {
  if (!moveLog) {
    return;
  }
  moveLog.textContent = "";
  moveHistory.forEach((entry, index) => {
    const item = document.createElement("div");
    item.className = "gamelog-item";
    item.textContent = `${index + 1}. ${entry}`;
    moveLog.appendChild(item);
  });
  moveLog.scrollTop = moveLog.scrollHeight;
}

if (gameMode === "seats") {
  seatPlayer = 0;
  viewPlayer = 0;
}
startPolling();
