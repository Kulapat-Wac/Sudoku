"""
Sudoku generator.

Makes Sudoku puzzles that always have exactly one solution.

Command line:
    python3 sudoku-generator.py              # medium puzzle
    python3 sudoku-generator.py -d hard      # choose difficulty
    python3 sudoku-generator.py --json       # JSON output (used by the website)
    python3 sudoku-generator.py --seed 42    # same puzzle every time

From other code (the hyphen in the file name means we need importlib):
    import importlib
    sudoku = importlib.import_module("sudoku-generator")
    data = sudoku.generate("hard")   # {"difficulty", "clues", "puzzle", "solution"}
"""

import argparse
import json
import random

# How many numbers are left on the board for each difficulty.
# Fewer numbers = harder puzzle.
DIFFICULTY_CLUES = {
    "easy": 40,
    "medium": 32,
    "hard": 27,
    "expert": 23,
}

# Hard puzzles can't always reach their target from one grid, so we try a few.
MAX_ATTEMPTS = 8


def get_candidates(board, row, col):
    """Return the numbers that can legally go in board[row][col]."""
    used = set(board[row])                          # numbers in the row
    used |= {board[r][col] for r in range(9)}       # numbers in the column

    box_row, box_col = 3 * (row // 3), 3 * (col // 3)
    for r in range(box_row, box_row + 3):           # numbers in the 3x3 box
        for c in range(box_col, box_col + 3):
            used.add(board[r][c])

    return [n for n in range(1, 10) if n not in used]


def find_best_empty_cell(board):
    """Return (row, col, candidates) for the empty cell with the fewest options,
    or None if the board is full. Filling the hardest cell first is much faster."""
    best = None
    for row in range(9):
        for col in range(9):
            if board[row][col] == 0:
                candidates = get_candidates(board, row, col)
                if best is None or len(candidates) < len(best[2]):
                    best = (row, col, candidates)
    return best


def fill_board(board):
    """Fill every empty cell with random valid numbers. Returns True on success."""
    cell = find_best_empty_cell(board)
    if cell is None:
        return True  # board is full

    row, col, candidates = cell
    random.shuffle(candidates)
    for number in candidates:
        board[row][col] = number
        if fill_board(board):
            return True
    board[row][col] = 0  # nothing fit, so undo and backtrack
    return False


def count_solutions(board, limit=2):
    """Count the board's solutions, stopping once we reach `limit`.
    We only need to know whether there is one solution or more than one."""
    cell = find_best_empty_cell(board)
    if cell is None:
        return 1  # board is full, so that's one solution

    row, col, candidates = cell
    total = 0
    for number in candidates:
        board[row][col] = number
        total += count_solutions(board, limit - total)
        if total >= limit:
            break
    board[row][col] = 0  # leave the board as we found it
    return total


def make_puzzle(target_clues):
    """Make one puzzle. Returns (puzzle, solution, clues)."""
    solution = [[0] * 9 for _ in range(9)]
    fill_board(solution)

    puzzle = [row[:] for row in solution]
    clues = 81

    cells = [(r, c) for r in range(9) for c in range(9)]
    random.shuffle(cells)

    for row, col in cells:
        if clues == target_clues:
            break
        removed = puzzle[row][col]
        puzzle[row][col] = 0
        if count_solutions(puzzle) == 1:
            clues -= 1
        else:
            puzzle[row][col] = removed  # puzzle would have 2+ answers, put it back

    return puzzle, solution, clues


def generate(difficulty="medium", seed=None):
    """Make a puzzle for the given difficulty. Returns a dict ready for JSON."""
    if difficulty not in DIFFICULTY_CLUES:
        raise ValueError(f"difficulty must be one of {list(DIFFICULTY_CLUES)}")
    random.seed(seed)
    target = DIFFICULTY_CLUES[difficulty]

    # Keep the attempt with the fewest clues; stop as soon as we hit the target.
    best = None
    for _ in range(MAX_ATTEMPTS):
        attempt = make_puzzle(target)
        if best is None or attempt[2] < best[2]:
            best = attempt
        if best[2] == target:
            break

    puzzle, solution, clues = best
    return {"difficulty": difficulty, "clues": clues, "puzzle": puzzle, "solution": solution}


def print_board(board):
    """Print the board with lines between the 3x3 boxes."""
    for row in range(9):
        if row in (3, 6):
            print("------+-------+------")
        line = ""
        for col in range(9):
            if col in (3, 6):
                line += "| "
            line += (str(board[row][col]) if board[row][col] else ".") + " "
        print(line.rstrip())


def main():
    parser = argparse.ArgumentParser(description="Generate a Sudoku puzzle.")
    parser.add_argument("-d", "--difficulty", choices=DIFFICULTY_CLUES, default="medium")
    parser.add_argument("--seed", type=int, help="use the same seed to get the same puzzle")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()

    data = generate(args.difficulty, args.seed)

    if args.json:
        print(json.dumps(data))
    else:
        print(f"Difficulty: {data['difficulty']} ({data['clues']} clues)\n")
        print("Puzzle:")
        print_board(data["puzzle"])
        print("\nSolution:")
        print_board(data["solution"])


if __name__ == "__main__":
    main()
