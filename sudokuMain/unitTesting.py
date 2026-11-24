"""
Unit tests for sudoku-generator.py and sudoku-checker.py.

Run from the sudokuMain folder:
    python3 -m unittest unitTesting -v
or simply:
    python3 unitTesting.py

What is tested:
  1. Arto Inkala's "world's hardest Sudoku" and known 17-clue puzzles
  2. The generator makes valid boards with exactly one solution
  3. Row, column and 3x3 box conflicts are flagged correctly
  4. Difficulty labels compared with the solving techniques a puzzle really needs
"""

import importlib
import os
import sys
import time
import unittest
from functools import lru_cache
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
generator = importlib.import_module("sudoku-generator")
checker = importlib.import_module("sudoku-checker")


def board(text):
    """Turn an 81-character string ('0' = empty) into a 9x9 list."""
    return [[int(text[r * 9 + c]) for c in range(9)] for r in range(9)]


def copy(grid):
    return [row[:] for row in grid]


def empty_grid():
    return [[0] * 9 for _ in range(9)]


def grid_with(number, *cells):
    """An empty grid with `number` written in each of the given cells."""
    grid = empty_grid()
    for r, c in cells:
        grid[r][c] = number
    return grid


# Arto Inkala's puzzle (2012), often called "the world's hardest Sudoku".
INKALA = board("800000000003600000070090200050007000000045700000100030001000068008500010090000400")
INKALA_SOLUTION = board("812753649943682175675491283154237896369845721287169534521974368438526917796318452")

# Puzzles with only 17 clues, the fewest a Sudoku with one solution can have
# (from Gordon Royle's collection of 17-clue puzzles).
SEVENTEEN_CLUE = [
    board("000000010400000000020000000000050407008000300001090000300400200050100000000806000"),
    board("000000010400000000020000000000050604008000300001090000300400200050100000000807000"),
    board("000000012000035000000600070700000300000400800100000000000120000080000040050000600"),
    board("000000012003600000000007000410020000000500300700000600280000040000300500000000000"),
]

DIFFICULTIES = list(generator.DIFFICULTY_CLUES)   # easy, medium, hard, expert
SEEDS = range(10)                                 # fixed seeds = repeatable tests
EVERY_CASE = [(d, s) for d in DIFFICULTIES for s in SEEDS]


# Puzzles are slow to make (expert ~1 s), so make each one once and reuse it.
@lru_cache(maxsize=None)
def generated(difficulty, seed):
    return generator.generate(difficulty, seed=seed)


# Technique-based rater: solves the puzzle the way a person would and reports
# the hardest technique it needed. Used to test the difficulty labels.

SINGLES, HIDDEN_SINGLES, INTERMEDIATE, ADVANCED = 1, 2, 3, 4
TECHNIQUE_NAMES = {SINGLES: "naked singles", HIDDEN_SINGLES: "hidden singles",
                   INTERMEDIATE: "locked candidates / naked pairs",
                   ADVANCED: "advanced techniques or guessing"}

ROWS = [[(r, c) for c in range(9)] for r in range(9)]
COLS = [[(r, c) for r in range(9)] for c in range(9)]
BOXES = [[(3 * (b // 3) + i, 3 * (b % 3) + j) for i in range(3) for j in range(3)] for b in range(9)]
UNITS = ROWS + COLS + BOXES
PEERS = {cell: {peer for unit in UNITS if cell in unit for peer in unit} - {cell}
         for unit in ROWS for cell in unit}


def rate_by_technique(puzzle):
    """Return the hardest technique needed: SINGLES, HIDDEN_SINGLES,
    INTERMEDIATE, or ADVANCED (cannot be solved with these techniques)."""
    grid = copy(puzzle)

    def empty(cell):
        return grid[cell[0]][cell[1]] == 0

    def value(cell):
        return grid[cell[0]][cell[1]]

    options = {cell: {value(cell)} if value(cell) else set(range(1, 10)) - {value(p) for p in PEERS[cell]}
               for cell in PEERS}

    def place(cell, number):
        grid[cell[0]][cell[1]] = number
        options[cell] = {number}
        for peer in PEERS[cell]:
            options[peer].discard(number)

    def remove(cells, numbers):
        """Remove numbers from the options of cells; True if anything changed."""
        changed = False
        for cell in cells:
            if options[cell] & numbers:
                options[cell] -= numbers
                changed = True
        return changed

    def naked_single():
        # A cell with only one possible number.
        for cell in options:
            if empty(cell) and len(options[cell]) == 1:
                return cell, next(iter(options[cell]))

    def hidden_single():
        # A number that fits in only one cell of a row, column or box.
        for unit in UNITS:
            for number in range(1, 10):
                spots = [cell for cell in unit if empty(cell) and number in options[cell]]
                if len(spots) == 1:
                    return spots[0], number

    def intermediate():
        # Locked candidates and naked pairs remove options.
        changed = False
        for box in BOXES:
            for line in ROWS + COLS:
                overlap = set(box) & set(line)
                if not overlap:
                    continue
                for number in range(1, 10):
                    in_box = {c for c in box if empty(c) and number in options[c]}
                    in_line = {c for c in line if empty(c) and number in options[c]}
                    if in_box and in_box <= overlap:      # pointing
                        changed |= remove(in_line - overlap, {number})
                    if in_line and in_line <= overlap:    # claiming
                        changed |= remove(in_box - overlap, {number})
        for unit in UNITS:
            cells = [c for c in unit if empty(c)]
            for a, b in combinations(cells, 2):
                if len(options[a]) == 2 and options[a] == options[b]:
                    others = [c for c in cells if c not in (a, b)]
                    changed |= remove(others, set(options[a]))
        return changed

    hardest = 0
    while any(0 in row for row in grid):
        if move := naked_single():
            place(*move)
            level = SINGLES
        elif move := hidden_single():
            place(*move)
            level = HIDDEN_SINGLES
        elif intermediate():
            level = INTERMEDIATE
        else:
            return ADVANCED   # stuck: needs harder techniques or trial and error
        hardest = max(hardest, level)
    return hardest


# 1. Stress tests: Arto Inkala and 17-clue puzzles

class TestHardPuzzles(unittest.TestCase):

    def test_inkala_has_exactly_one_solution(self):
        self.assertEqual(generator.count_solutions(copy(INKALA)), 1)
        self.assertEqual(len(checker.find_solutions(INKALA, limit=2)), 1)

    def test_inkala_solved_correctly(self):
        solution = checker.find_solutions(INKALA, limit=1)[0]
        self.assertEqual(solution, INKALA_SOLUTION)
        self.assertTrue(checker.is_solved(solution))

    def test_inkala_passes_full_check(self):
        data = {"puzzle": INKALA, "solution": INKALA_SOLUTION, "clues": 21}
        self.assertEqual(checker.check_generated(data), [])

    def test_inkala_needs_advanced_techniques(self):
        self.assertEqual(rate_by_technique(INKALA), ADVANCED)

    def test_inkala_solves_quickly(self):
        start = time.time()
        checker.find_solutions(INKALA, limit=2)
        self.assertLess(time.time() - start, 10, "solver too slow on Inkala's puzzle")

    def test_seventeen_clue_puzzles_have_one_solution(self):
        for i, puzzle in enumerate(SEVENTEEN_CLUE):
            with self.subTest(puzzle=i):
                self.assertEqual(checker.count_clues(puzzle), 17)
                self.assertEqual(generator.count_solutions(copy(puzzle)), 1)
                solutions = checker.find_solutions(puzzle, limit=2)
                self.assertEqual(len(solutions), 1)
                self.assertTrue(checker.is_solved(solutions[0]))

    def test_seventeen_clue_solutions_keep_the_clues(self):
        for i, puzzle in enumerate(SEVENTEEN_CLUE):
            with self.subTest(puzzle=i):
                solution = checker.find_solutions(puzzle, limit=1)[0]
                self.assertTrue(all(solution[r][c] == puzzle[r][c]
                                    for r in range(9) for c in range(9) if puzzle[r][c]))

    def test_sixteen_clues_is_not_unique(self):
        # Removing any clue from a 17-clue puzzle must give more than one solution.
        puzzle = copy(SEVENTEEN_CLUE[0])
        r, c = next((r, c) for r in range(9) for c in range(9) if puzzle[r][c])
        puzzle[r][c] = 0
        self.assertEqual(generator.count_solutions(copy(puzzle)), 2)
        self.assertIn("only 16 clues (need at least 17)",
                      checker.check_generated({"puzzle": puzzle, "solution": INKALA_SOLUTION}))

    def test_empty_board_is_not_unique(self):
        self.assertEqual(generator.count_solutions(empty_grid()), 2)


# 2. Generator makes valid boards with a single solution

class TestGenerator(unittest.TestCase):

    def test_puzzles_have_exactly_one_solution(self):
        for difficulty, seed in EVERY_CASE:
            with self.subTest(difficulty=difficulty, seed=seed):
                puzzle = generated(difficulty, seed)["puzzle"]
                self.assertEqual(len(checker.find_solutions(puzzle, limit=2)), 1)

    def test_solution_is_a_valid_complete_board(self):
        for difficulty, seed in EVERY_CASE:
            with self.subTest(difficulty=difficulty, seed=seed):
                self.assertTrue(checker.is_solved(generated(difficulty, seed)["solution"]))

    def test_unique_solution_is_the_returned_one(self):
        for difficulty, seed in EVERY_CASE:
            with self.subTest(difficulty=difficulty, seed=seed):
                data = generated(difficulty, seed)
                self.assertEqual(checker.find_solutions(data["puzzle"], limit=1)[0], data["solution"])

    def test_passes_full_checker(self):
        for difficulty, seed in EVERY_CASE:
            with self.subTest(difficulty=difficulty, seed=seed):
                self.assertEqual(checker.check_generated(generated(difficulty, seed)), [])

    def test_clue_count_close_to_target(self):
        for difficulty, seed in EVERY_CASE:
            with self.subTest(difficulty=difficulty, seed=seed):
                target = generator.DIFFICULTY_CLUES[difficulty]
                self.assertIn(generated(difficulty, seed)["clues"], range(target, target + 3))

    def test_same_seed_gives_same_puzzle(self):
        self.assertEqual(generator.generate("medium", seed=7), generator.generate("medium", seed=7))

    def test_different_seeds_give_different_puzzles(self):
        self.assertNotEqual(generated("easy", 0)["puzzle"], generated("easy", 1)["puzzle"])

    def test_full_grid_is_valid(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                generator.random.seed(seed)
                grid = empty_grid()
                self.assertTrue(generator.fill_board(grid))
                self.assertTrue(checker.is_solved(grid))

    def test_unknown_difficulty_is_rejected(self):
        with self.assertRaises(ValueError):
            generator.generate("impossible")


# 3. Row, column and 3x3 box conflicts

class TestConflicts(unittest.TestCase):

    def test_solved_board_has_no_conflicts(self):
        self.assertEqual(checker.find_conflicts(INKALA_SOLUTION), [])
        self.assertTrue(checker.is_solved(INKALA_SOLUTION))

    def test_row_conflict(self):
        cells = [(4, 0), (4, 8)]            # same row, different columns and boxes
        self.assertEqual(checker.find_conflicts(grid_with(5, *cells)), cells)

    def test_column_conflict(self):
        cells = [(0, 6), (8, 6)]            # same column, different rows and boxes
        self.assertEqual(checker.find_conflicts(grid_with(3, *cells)), cells)

    def test_box_conflict(self):
        cells = [(3, 3), (5, 5)]            # same box, different row and column
        self.assertEqual(checker.find_conflicts(grid_with(9, *cells)), cells)

    def test_no_conflict_for_different_groups(self):
        grid = grid_with(7, (0, 0), (4, 4))  # different row, column and box
        self.assertEqual(checker.find_conflicts(grid), [])

    def test_triple_conflict_flags_all_three(self):
        cells = [(0, 0), (0, 5), (7, 0)]    # row clash and column clash share (0, 0)
        self.assertEqual(checker.find_conflicts(grid_with(2, *cells)), cells)

    def test_box_only_errors_are_caught(self):
        # Every row and column holds 1-9, but the 3x3 boxes repeat numbers.
        grid = [[(r + c) % 9 + 1 for c in range(9)] for r in range(9)]
        for line in grid + [list(col) for col in zip(*grid)]:
            self.assertEqual(sorted(line), list(range(1, 10)))
        self.assertFalse(checker.is_solved(grid))
        self.assertTrue(checker.find_conflicts(grid))

    def test_swapped_cells_break_the_solution(self):
        grid = copy(INKALA_SOLUTION)
        grid[0][0], grid[0][1] = grid[0][1], grid[0][0]   # row still fine, columns break
        self.assertFalse(checker.is_solved(grid))
        self.assertIn((0, 0), checker.find_conflicts(grid))

    def test_generator_candidates_skip_row_column_and_box(self):
        grid = empty_grid()
        grid[0][8] = 1      # same row as (0, 0)
        grid[8][0] = 2      # same column
        grid[2][2] = 3      # same box
        grid[5][5] = 4      # unrelated cell
        self.assertEqual(generator.get_candidates(grid, 0, 0), [4, 5, 6, 7, 8, 9])
        self.assertEqual(checker.get_candidates(grid, 0, 0), [4, 5, 6, 7, 8, 9])

    def test_conflicting_puzzle_has_no_solution(self):
        puzzle = copy(INKALA)
        puzzle[0][1] = 8    # second 8 in row 0
        self.assertEqual(checker.find_solutions(puzzle), [])
        self.assertIn("puzzle has no solution",
                      checker.check_generated({"puzzle": puzzle, "solution": INKALA_SOLUTION}))

    def test_player_board_statuses(self):
        def status(board):
            return checker.check_player_board(INKALA, board)

        self.assertEqual(status(copy(INKALA))["status"], "in_progress")
        self.assertEqual(status(INKALA_SOLUTION)["status"], "solved")

        clash = copy(INKALA)
        clash[0][1] = 8     # player types a second 8 in the first row
        self.assertEqual(status(clash), {"status": "in_progress", "conflicts": [(0, 0), (0, 1)]})

        changed_clue = copy(INKALA_SOLUTION)
        changed_clue[0][0] = 1  # overwrites the given 8
        self.assertEqual(status(changed_clue)["status"], "invalid")


# 4. Difficulty labels vs. the solving techniques really needed

class TestDifficulty(unittest.TestCase):

    def rating(self, difficulty, seed):
        return rate_by_technique(generated(difficulty, seed)["puzzle"])

    def test_rater_on_reference_puzzles(self):
        # A board with one empty cell needs only a naked single.
        one_gap = copy(INKALA_SOLUTION)
        one_gap[4][4] = 0
        self.assertEqual(rate_by_technique(one_gap), SINGLES)
        self.assertEqual(rate_by_technique(INKALA), ADVANCED)

    def test_fewer_clues_for_harder_levels(self):
        targets = [generator.DIFFICULTY_CLUES[d] for d in DIFFICULTIES]
        self.assertEqual(targets, sorted(targets, reverse=True))

    def test_easy_needs_only_naked_singles(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(self.rating("easy", seed), SINGLES)

    def test_harder_labels_need_harder_techniques_on_average(self):
        averages = [sum(self.rating(d, s) for s in SEEDS) / len(SEEDS) for d in DIFFICULTIES]
        self.assertEqual(averages, sorted(averages), f"average technique level per label: {averages}")

    def test_expert_is_never_singles_only(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertGreater(self.rating("expert", seed), SINGLES)

    @unittest.expectedFailure
    def test_every_puzzle_matches_its_label(self):
        """KNOWN GAP: the generator sets difficulty by clue count only, so some
        'medium' puzzles need advanced techniques and some 'hard' ones need only
        singles. Remove @expectedFailure once the generator rates puzzles by
        technique; this test will then have to pass."""
        allowed = {
            "easy":   {SINGLES},
            "medium": {SINGLES, HIDDEN_SINGLES},
            "hard":   {HIDDEN_SINGLES, INTERMEDIATE},
            "expert": {INTERMEDIATE, ADVANCED},
        }
        mismatches = [f"{d} seed {s}: needs {TECHNIQUE_NAMES[self.rating(d, s)]}"
                      for d, s in EVERY_CASE if self.rating(d, s) not in allowed[d]]
        self.assertEqual(mismatches, [], "\n" + "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main(verbosity=2)
