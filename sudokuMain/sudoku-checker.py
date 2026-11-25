"""
Sudoku checker.

Checks puzzles made by sudoku-generator.py. It has its own solver, so a bug
in the generator can't hide itself.

For each puzzle it checks that:
  1. the puzzle and solution are 9x9 grids of numbers 0-9
  2. the solution follows the Sudoku rules
  3. every clue in the puzzle matches the solution
  4. the puzzle has exactly one solution, and it is the given one
  5. there are at least 17 clues and the "clues" count is right

Command line:
    python3 sudoku-checker.py                  # make and check 10 puzzles per difficulty
    python3 sudoku-checker.py -n 50 -d hard    # 50 hard puzzles
    python3 sudoku-generator.py --json | python3 sudoku-checker.py -   # check piped JSON
    python3 sudoku-checker.py puzzle.json      # check a JSON file

From other code:
    import importlib
    checker = importlib.import_module("sudoku-checker")
    errors = checker.check_generated(data)               # [] means OK
    checker.check_player_board(puzzle, player_board)     # for the website
"""

import argparse
import importlib
import json
import sys

MIN_CLUES = 17  # fewest clues a puzzle with one solution can have


# ---------- Basic helpers ----------

def is_valid_grid(board, allow_empty=True):
    """True if board is a 9x9 list of whole numbers (0 allowed only if allow_empty)."""
    smallest = 0 if allow_empty else 1
    return (
        isinstance(board, list) and len(board) == 9
        and all(isinstance(row, list) and len(row) == 9 for row in board)
        and all(type(n) is int and smallest <= n <= 9 for row in board for n in row)
    )


def get_groups():
    """Return all 27 groups of cells that must not repeat a number:
    9 rows, 9 columns and 9 boxes. Each group is a list of (row, col)."""
    groups = []
    for i in range(9):
        groups.append([(i, c) for c in range(9)])     # row i
        groups.append([(r, i) for r in range(9)])     # column i
        box_row, box_col = 3 * (i // 3), 3 * (i % 3)
        groups.append([(box_row + r, box_col + c)     # box i
                       for r in range(3) for c in range(3)])
    return groups


GROUPS = get_groups()


def find_conflicts(board):
    """Return a sorted list of cells whose number appears twice in a row,
    column or box. The website can highlight these in red."""
    conflicts = set()
    for group in GROUPS:
        seen = {}  # number -> first cell where we saw it
        for row, col in group:
            number = board[row][col]
            if number == 0:
                continue
            if number in seen:
                conflicts.add(seen[number])
                conflicts.add((row, col))
            else:
                seen[number] = (row, col)
    return sorted(conflicts)


def is_solved(board):
    """True if every row, column and box contains 1-9 exactly once."""
    return all({board[r][c] for r, c in group} == set(range(1, 10)) for group in GROUPS)


def count_clues(board):
    return sum(1 for row in board for n in row if n != 0)


# ---------- Solver ----------

def get_candidates(board, row, col):
    """Return the numbers that can legally go in board[row][col]."""
    used = set(board[row]) | {board[r][col] for r in range(9)}
    box_row, box_col = 3 * (row // 3), 3 * (col // 3)
    used |= {board[r][c] for r in range(box_row, box_row + 3)
                         for c in range(box_col, box_col + 3)}
    return [n for n in range(1, 10) if n not in used]


def find_solutions(puzzle, limit=2):
    """Return up to `limit` solutions of the puzzle (2 is enough to spot a
    puzzle with more than one answer)."""
    board = [row[:] for row in puzzle]
    solutions = []

    def solve():
        # Pick the empty cell with the fewest options; it's the fastest to try.
        best = None
        for row in range(9):
            for col in range(9):
                if board[row][col] == 0:
                    options = get_candidates(board, row, col)
                    if best is None or len(options) < len(best[2]):
                        best = (row, col, options)

        if best is None:  # no empty cells: found a solution
            solutions.append([r[:] for r in board])
            return

        row, col, options = best
        for number in options:
            board[row][col] = number
            solve()
            if len(solutions) >= limit:
                return
        board[row][col] = 0

    if not find_conflicts(board):
        solve()
    return solutions


# ---------- Main checks ----------

def check_generated(data):
    """Check a dict from generate(). Returns a list of problems ([] = all good)."""
    puzzle, solution = data.get("puzzle"), data.get("solution")

    if not is_valid_grid(puzzle):
        return ["puzzle is not a 9x9 grid of numbers 0-9"]
    if not is_valid_grid(solution, allow_empty=False):
        return ["solution is not a 9x9 grid of numbers 1-9"]

    errors = []
    clues = count_clues(puzzle)
    if clues < MIN_CLUES:
        errors.append(f"only {clues} clues (need at least {MIN_CLUES})")
    if data.get("clues", clues) != clues:
        errors.append(f"says {data['clues']} clues but has {clues}")
    if not is_solved(solution):
        errors.append("solution breaks the Sudoku rules")
    if any(puzzle[r][c] not in (0, solution[r][c]) for r in range(9) for c in range(9)):
        errors.append("some puzzle clues don't match the solution")

    solutions = find_solutions(puzzle)
    if len(solutions) == 0:
        errors.append("puzzle has no solution")
    elif len(solutions) > 1:
        errors.append("puzzle has more than one solution")
    elif solutions[0] != solution:
        errors.append("puzzle's real solution is different from the given one")

    return errors


def check_player_board(puzzle, board):
    """Check a player's board during a game.
    Returns {"status": "solved" | "in_progress" | "invalid", "conflicts": [...]}"""
    if not is_valid_grid(board):
        return {"status": "invalid", "conflicts": []}

    changed_clue = any(puzzle[r][c] not in (0, board[r][c]) for r in range(9) for c in range(9))
    if changed_clue:
        return {"status": "invalid", "conflicts": []}

    conflicts = find_conflicts(board)
    status = "solved" if is_solved(board) else "in_progress"
    return {"status": status, "conflicts": conflicts}


# ---------- Command line ----------

def check_and_report(name, data):
    """Check one puzzle, print PASS/FAIL, and return True if it passed."""
    errors = check_generated(data)
    if errors:
        print(f"FAIL  {name}: " + "; ".join(errors))
    return not errors


def main():
    parser = argparse.ArgumentParser(description="Check Sudoku puzzles.")
    parser.add_argument("file", nargs="?", help="JSON file to check, or '-' for piped input")
    parser.add_argument("-n", "--count", type=int, default=10, help="puzzles per difficulty")
    parser.add_argument("-d", "--difficulty", action="append", help="difficulty to test")
    args = parser.parse_args()

    all_passed = True

    if args.file:
        # Check puzzles from a file or from piped input.
        if args.file == "-":
            puzzles = json.load(sys.stdin)
        else:
            with open(args.file) as f:
                puzzles = json.load(f)
        if isinstance(puzzles, dict):
            puzzles = [puzzles]
        for i, data in enumerate(puzzles, 1):
            passed = check_and_report(f"#{i}", data)
            if passed:
                print(f"PASS  #{i} ({data.get('difficulty', '?')}, {data.get('clues')} clues)")
            all_passed = all_passed and passed
    else:
        # Make new puzzles with the generator and check them.
        generator = importlib.import_module("sudoku-generator")
        for difficulty in args.difficulty or generator.DIFFICULTY_CLUES:
            passed = 0
            for i in range(args.count):
                if check_and_report(f"{difficulty} #{i + 1}", generator.generate(difficulty)):
                    passed += 1
            print(f"{'PASS' if passed == args.count else 'FAIL'}  {difficulty:<7} {passed}/{args.count}")
            all_passed = all_passed and passed == args.count

    print("\nAll checks passed." if all_passed else "\nSome checks FAILED.")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
