(() => {
  const tetrisView = document.getElementById("tetrisView");
  if (!tetrisView) {
    return;
  }

  const boardEl = document.getElementById("tetrisBoard");
  const nextEl = document.getElementById("tetrisNext");
  const statsEl = document.getElementById("tetrisStats");
  const statusEl = document.getElementById("tetrisStatus");
  const mobileControls = document.getElementById("tetrisMobileControls");
  const gameModal = document.getElementById("gameModal");
  const modalTitle = document.getElementById("modalTitle");
  const modalBody = document.getElementById("modalBody");
  const newGameBtn = document.getElementById("newGameBtn");

  const width = 10;
  const height = 20;
  const softDropInterval = 60;
  const lineScores = [0, 100, 300, 500, 800];
  const pieceTypes = ["I", "O", "T", "S", "Z", "J", "L"];

  const shapes = {
    I: [
      [[0, 1], [1, 1], [2, 1], [3, 1]],
      [[2, 0], [2, 1], [2, 2], [2, 3]],
      [[0, 2], [1, 2], [2, 2], [3, 2]],
      [[1, 0], [1, 1], [1, 2], [1, 3]],
    ],
    O: [
      [[1, 0], [2, 0], [1, 1], [2, 1]],
      [[1, 0], [2, 0], [1, 1], [2, 1]],
      [[1, 0], [2, 0], [1, 1], [2, 1]],
      [[1, 0], [2, 0], [1, 1], [2, 1]],
    ],
    T: [
      [[1, 0], [0, 1], [1, 1], [2, 1]],
      [[1, 0], [1, 1], [2, 1], [1, 2]],
      [[0, 1], [1, 1], [2, 1], [1, 2]],
      [[1, 0], [0, 1], [1, 1], [1, 2]],
    ],
    S: [
      [[1, 0], [2, 0], [0, 1], [1, 1]],
      [[1, 0], [1, 1], [2, 1], [2, 2]],
      [[1, 1], [2, 1], [0, 2], [1, 2]],
      [[0, 0], [0, 1], [1, 1], [1, 2]],
    ],
    Z: [
      [[0, 0], [1, 0], [1, 1], [2, 1]],
      [[2, 0], [1, 1], [2, 1], [1, 2]],
      [[0, 1], [1, 1], [1, 2], [2, 2]],
      [[1, 0], [0, 1], [1, 1], [0, 2]],
    ],
    J: [
      [[0, 0], [0, 1], [1, 1], [2, 1]],
      [[1, 0], [2, 0], [1, 1], [1, 2]],
      [[0, 1], [1, 1], [2, 1], [2, 2]],
      [[1, 0], [1, 1], [0, 2], [1, 2]],
    ],
    L: [
      [[2, 0], [0, 1], [1, 1], [2, 1]],
      [[1, 0], [1, 1], [1, 2], [2, 2]],
      [[0, 1], [1, 1], [2, 1], [0, 2]],
      [[0, 0], [1, 0], [1, 1], [1, 2]],
    ],
  };

  let board = createBoard();
  let currentPiece = null;
  let nextPiece = null;
  let bag = [];
  let score = 0;
  let lines = 0;
  let level = 1;
  let dropTimer = null;
  let currentInterval = null;
  let softDropActive = false;
  let gameOver = false;
  let boardCells = [];
  let nextCells = [];

  function createBoard() {
    return Array.from({ length: height }, () => Array(width).fill(""));
  }

  function buildGrid(container, rows, cols) {
    const cells = [];
    if (!container) {
      return cells;
    }
    container.innerHTML = "";
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < cols; x += 1) {
        const cell = document.createElement("div");
        cell.className = "tetris-cell";
        container.appendChild(cell);
        cells.push(cell);
      }
    }
    return cells;
  }

  function shuffle(values) {
    const copy = values.slice();
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  function drawFromBag() {
    if (bag.length === 0) {
      bag = shuffle(pieceTypes);
    }
    return bag.pop();
  }

  function makePiece() {
    return {
      type: drawFromBag(),
      rotation: 0,
      x: 3,
      y: -2,
    };
  }

  function getCells(piece, rotationOverride = null) {
    const rotation = rotationOverride == null ? piece.rotation : rotationOverride;
    return shapes[piece.type][rotation].map(([x, y]) => ({
      x: piece.x + x,
      y: piece.y + y,
    }));
  }

  function isValidPosition(piece, dx = 0, dy = 0, rotationOverride = null) {
    const cells = getCells(piece, rotationOverride);
    return cells.every(({ x, y }) => {
      const nextX = x + dx;
      const nextY = y + dy;
      if (nextX < 0 || nextX >= width || nextY >= height) {
        return false;
      }
      if (nextY < 0) {
        return true;
      }
      return board[nextY][nextX] === "";
    });
  }

  function spawnPiece() {
    if (!nextPiece) {
      nextPiece = makePiece();
    }
    currentPiece = nextPiece;
    currentPiece.x = 3;
    currentPiece.y = -2;
    currentPiece.rotation = 0;
    nextPiece = makePiece();
    if (!isValidPosition(currentPiece)) {
      handleGameOver();
    }
  }

  function movePiece(dx, dy) {
    if (!currentPiece || gameOver) {
      return false;
    }
    if (isValidPosition(currentPiece, dx, dy)) {
      currentPiece.x += dx;
      currentPiece.y += dy;
      render();
      return true;
    }
    return false;
  }

  function rotatePiece(direction) {
    if (!currentPiece || gameOver) {
      return;
    }
    const nextRotation = (currentPiece.rotation + direction + 4) % 4;
    const kicks = [0, -1, 1, -2, 2];
    for (const offset of kicks) {
      if (isValidPosition(currentPiece, offset, 0, nextRotation)) {
        currentPiece.rotation = nextRotation;
        currentPiece.x += offset;
        render();
        return;
      }
    }
  }

  function lockPiece() {
    if (!currentPiece) {
      return;
    }
    const cells = getCells(currentPiece);
    let hasAbove = false;
    cells.forEach(({ x, y }) => {
      if (y < 0) {
        hasAbove = true;
        return;
      }
      board[y][x] = currentPiece.type;
    });
    if (hasAbove) {
      handleGameOver();
      return;
    }
    clearLines();
    spawnPiece();
    render();
  }

  function clearLines() {
    let cleared = 0;
    for (let y = height - 1; y >= 0; y -= 1) {
      if (board[y].every((cell) => cell !== "")) {
        board.splice(y, 1);
        board.unshift(Array(width).fill(""));
        cleared += 1;
        y += 1;
      }
    }
    if (cleared > 0) {
      lines += cleared;
      score += lineScores[cleared] * level;
      level = Math.floor(lines / 10) + 1;
      updateStats();
      refreshDropTimer();
    }
  }

  function getBaseInterval() {
    return Math.max(120, 800 - (level - 1) * 60);
  }

  function refreshDropTimer() {
    const target = softDropActive ? softDropInterval : getBaseInterval();
    if (currentInterval === target) {
      return;
    }
    if (dropTimer) {
      clearInterval(dropTimer);
    }
    currentInterval = target;
    dropTimer = setInterval(() => {
      if (!gameOver) {
        stepDown();
      }
    }, target);
  }

  function stepDown() {
    if (!movePiece(0, 1)) {
      lockPiece();
    }
  }

  function setSoftDrop(active) {
    if (softDropActive === active) {
      return;
    }
    softDropActive = active;
    refreshDropTimer();
  }

  function updateStats() {
    if (!statsEl) {
      return;
    }
    statsEl.textContent = `score://${score} | lines://${lines} | level://${level}`;
  }

  function updateStatus(text) {
    if (!statusEl) {
      return;
    }
    statusEl.textContent = `status://${text}`;
  }

  function render() {
    if (!boardCells.length) {
      return;
    }
    boardCells.forEach((cell) => {
      cell.className = "tetris-cell";
    });
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const type = board[y][x];
        if (type !== "") {
          const cell = boardCells[y * width + x];
          cell.classList.add("filled", `piece-${type}`);
        }
      }
    }
    if (currentPiece) {
      getCells(currentPiece).forEach(({ x, y }) => {
        if (y < 0) {
          return;
        }
        const cell = boardCells[y * width + x];
        cell.classList.add("filled", `piece-${currentPiece.type}`);
      });
    }
    renderNext();
  }

  function renderNext() {
    if (!nextCells.length || !nextPiece) {
      return;
    }
    nextCells.forEach((cell) => {
      cell.className = "tetris-cell";
    });
    const preview = shapes[nextPiece.type][0];
    preview.forEach(([x, y]) => {
      const index = y * 4 + x;
      const cell = nextCells[index];
      if (cell) {
        cell.classList.add("filled", `piece-${nextPiece.type}`);
      }
    });
  }

  function handleGameOver() {
    gameOver = true;
    updateStatus("game over");
    if (dropTimer) {
      clearInterval(dropTimer);
    }
    if (gameModal && modalTitle && modalBody) {
      modalTitle.textContent = "Game Over";
      modalBody.textContent = `Score ${score} | Lines ${lines} | Level ${level}`;
      gameModal.classList.add("open");
      gameModal.setAttribute("aria-hidden", "false");
    }
  }

  function startGame() {
    board = createBoard();
    score = 0;
    lines = 0;
    level = 1;
    gameOver = false;
    bag = [];
    currentPiece = null;
    nextPiece = null;
    updateStats();
    updateStatus("running");
    if (gameModal) {
      gameModal.classList.remove("open");
      gameModal.setAttribute("aria-hidden", "true");
    }
    spawnPiece();
    render();
    refreshDropTimer();
  }

  function handleKeyDown(event) {
    if (gameOver) {
      return;
    }
    const key = event.key.toLowerCase();
    if (["arrowleft", "arrowright", "arrowdown", "a", "d", "s"].includes(key)) {
      event.preventDefault();
    }
    if (key === "arrowleft") {
      movePiece(-1, 0);
    } else if (key === "arrowright") {
      movePiece(1, 0);
    } else if (key === "a") {
      rotatePiece(-1);
    } else if (key === "d") {
      rotatePiece(1);
    } else if (key === "s" || key === "arrowdown") {
      setSoftDrop(true);
    }
  }

  function handleKeyUp(event) {
    const key = event.key.toLowerCase();
    if (key === "s" || key === "arrowdown") {
      setSoftDrop(false);
    }
  }

  if (newGameBtn) {
    newGameBtn.addEventListener("click", () => {
      startGame();
    });
  }

  document.addEventListener("keydown", handleKeyDown);
  document.addEventListener("keyup", handleKeyUp);

  if (mobileControls) {
    mobileControls.querySelectorAll("button[data-action]").forEach((button) => {
      const action = button.dataset.action;
      if (action === "rotate-left") {
        button.addEventListener("click", () => rotatePiece(-1));
      } else if (action === "rotate-right") {
        button.addEventListener("click", () => rotatePiece(1));
      } else if (action === "move-left") {
        button.addEventListener("click", () => movePiece(-1, 0));
      } else if (action === "move-right") {
        button.addEventListener("click", () => movePiece(1, 0));
      } else if (action === "soft-drop") {
        button.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          setSoftDrop(true);
        });
        const stopDrop = () => setSoftDrop(false);
        button.addEventListener("pointerup", stopDrop);
        button.addEventListener("pointerleave", stopDrop);
        button.addEventListener("pointercancel", stopDrop);
      }
    });
  }

  boardCells = buildGrid(boardEl, height, width);
  nextCells = buildGrid(nextEl, 4, 4);
  startGame();
})();
