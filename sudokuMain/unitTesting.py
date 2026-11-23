"""
Unit tests for sudoku-generator.py and sudoku-checker.py.

Run from the sudokuMain folder:
    python3 -m unittest unitTesting -v
or simply:
    python3 unitTesting.py

What is tested:
  1. Arto Inkala's "world's hardest Sudoku" and known 17-clue puzzles (stress test)
  2. The generator makes valid boards with exactly one solution
  3. Row, column and 3x3 box conflicts are flagged correctly
  4. Difficulty labels compared with the solving techniques a puzzle really needs
"""

import importlib
import os
import sys
import time
import unittest
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
generator = importlib.import_module("sudoku-generator")
checker = importlib.import_module("sudoku-checker")


def board(text):
    """Turn an 81-character string ('0' or '.' = empty) into a 9x9 list."""
    text = text.replace(".", "0")
    return [[int(text[r * 9 + c]) for c in range(9)] for r in range(9)]


def copy(grid):
    return [row[:] for row in grid]


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

# A correct, complete grid used as a starting point for conflict tests.
SOLVED = copy(INKALA_SOLUTION)

DIFFICULTIES = list(generator.DIFFICULTY_CLUES)  # easy, medium, hard, expert
SEEDS = range(10)                                # fixed seeds = repeatable tests


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
PEERS = {(r, c): {cell for unit in UNITS if (r, c) in unit for cell in unit} - {(r, c)}
         for r in range(9) for c in range(9)}


def rate_by_technique(puzzle):
    """Return the hardest technique needed: SINGLES, HIDDEN_SINGLES,
    INTERMEDIATE, or ADVANCED (cannot be solved with these techniques)."""
    grid = copy(puzzle)
    empty = lambda cell: grid[cell[0]][cell[1]] == 0
    options = {cell: ({grid[cell[0]][cell[1]]} if not empty(cell)
                      else set(range(1, 10)) - {grid[r][c] for r, c in PEERS[cell]})
               for cell in PEERS}

    def place(cell, number):
        grid[cell[0]][cell[1]] = number
        options[cell] = {number}
        for peer in PEERS[cell]:
            options[peer].discard(number)

    hardest = 0
    while any(0 in row for row in grid):
        # 1. Naked single: a cell with only one possible number.
        cell = next((c for c in options if empty(c) and len(options[c]) == 1), None)
        if cell:
            place(cell, next(iter(options[cell])))
            hardest = max(hardest, SINGLES)
            continue

        # 2. Hidden single: a number that fits in only one cell of a group.
        placed = False
        for unit in UNITS:
            for number in range(1, 10):
                if any(grid[r][c] == number for r, c in unit):
                    continue
                spots = [c for c in unit if empty(c) and number in options[c]]
                if len(spots) == 1:
                    place(spots[0], number)
                    placed = True
                    break
            if placed:
                break
        if placed:
            hardest = max(hardest, HIDDEN_SINGLES)
            continue

        # 3. Intermediate: locked candidates and naked pairs remove options.
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
                        for c in in_line - overlap:
                            options[c].discard(number)
                            changed = True
                    if in_line and in_line <= overlap:    # claiming
                        for c in in_box - overlap:
                            options[c].discard(number)
                            changed = True
        for unit in UNITS:
            cells = [c for c in unit if empty(c)]
            for a, b in combinations(cells, 2):
                if len(options[a]) == 2 and options[a] == options[b]:
                    for c in cells:
                        if c not in (a, b) and options[c] & options[a]:
                            options[c] -= options[a]
                            changed = True
        if changed:
            hardest = max(hardest, INTERMEDIATE)
            continue

        return ADVANCED  # stuck: needs harder techniques or trial and error
    return hardest


# Puzzles are slow to make (expert ~1 s), so make each one once and share it.
_cache = {}


def generated(difficulty, seed):
    if (difficulty, seed) not in _cache:
        _cache[(difficulty, seed)] = generator.generate(difficulty, seed=seed)
    return _cache[(difficulty, seed)]


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
                for r in range(9):
                    for c in range(9):
                        if puzzle[r][c]:
                            self.assertEqual(solution[r][c], puzzle[r][c])

    def test_sixteen_clues_is_not_unique(self):
        # Removing any clue from a 17-clue puzzle must give more than one solution.
        puzzle = copy(SEVENTEEN_CLUE[0])
        r, c = next((r, c) for r in range(9) for c in range(9) if puzzle[r][c])
        puzzle[r][c] = 0
        self.assertEqual(generator.count_solutions(copy(puzzle)), 2)
        self.assertIn("only 16 clues (need at least 17)",
                      checker.check_generated({"puzzle": puzzle, "solution": SOLVED}))

    def test_empty_board_is_not_unique(self):
        empty = [[0] * 9 for _ in range(9)]
        self.assertEqual(generator.count_solutions(copy(empty)), 2)


# 2. Generator makes valid boards with a single solution

class TestGenerator(unittest.TestCase):

    def test_puzzles_have_exactly_one_solution(self):
        for difficulty in DIFFICULTIES:
            for seed in SEEDS:
                with self.subTest(difficulty=difficulty, seed=seed):
                    data = generated(difficulty, seed)
                    self.assertEqual(len(checker.find_solutions(data["puzzle"], limit=2)), 1)

    def test_solution_is_a_valid_complete_board(self):
        for difficulty in DIFFICULTIES:
            for seed in SEEDS:
                with self.subTest(difficulty=difficulty, seed=seed):
                    self.assertTrue(checker.is_solved(generated(difficulty, seed)["solution"]))

    def test_unique_solution_is_the_returned_one(self):
        for difficulty in DIFFICULTIES:
            for seed in SEEDS:
                with self.subTest(difficulty=difficulty, seed=seed):
                    data = generated(difficulty, seed)
                    self.assertEqual(checker.find_solutions(data["puzzle"], limit=1)[0], data["solution"])

    def test_passes_full_checker(self):
        for difficulty in DIFFICULTIES:
            for seed in SEEDS:
                with self.subTest(difficulty=difficulty, seed=seed):
                    self.assertEqual(checker.check_generated(generated(difficulty, seed)), [])

    def test_clue_count_close_to_target(self):
        for difficulty, target in generator.DIFFICULTY_CLUES.items():
            for seed in SEEDS:
                with self.subTest(difficulty=difficulty, seed=seed):
                    clues = generated(difficulty, seed)["clues"]
                    self.assertGreaterEqual(clues, target)
                    self.assertLessEqual(clues, target + 2)

    def test_same_seed_gives_same_puzzle(self):
        self.assertEqual(generator.generate("medium", seed=7), generator.generate("medium", seed=7))

    def test_different_seeds_give_different_puzzles(self):
        self.assertNotEqual(generated("easy", 0)["puzzle"], generated("easy", 1)["puzzle"])

    def test_full_grid_is_valid(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                generator.random.seed(seed)
                grid = [[0] * 9 for _ in range(9)]
                self.assertTrue(generator.fill_board(grid))
                self.assertTrue(checker.is_solved(grid))

    def test_unknown_difficulty_is_rejected(self):
        with self.assertRaises(ValueError):
            generator.generate("impossible")


# 3. Row, column and 3x3 box conflicts

class TestConflicts(unittest.TestCase):

    def test_solved_board_has_no_conflicts(self):
        self.assertEqual(checker.find_conflicts(SOLVED), [])
        self.assertTrue(checker.is_solved(SOLVED))

    def test_row_conflict(self):
        grid = [[0] * 9 for _ in range(9)]
        grid[4][0] = grid[4][8] = 5            # same row, different columns and boxes
        self.assertEqual(checker.find_conflicts(grid), [(4, 0), (4, 8)])

    def test_column_conflict(self):
        grid = [[0] * 9 for _ in range(9)]
        grid[0][6] = grid[8][6] = 3            # same column, different rows and boxes
        self.assertEqual(checker.find_conflicts(grid), [(0, 6), (8, 6)])

    def test_box_conflict(self):
        grid = [[0] * 9 for _ in range(9)]
        grid[3][3] = grid[5][5] = 9            # same box, different row and column
        self.assertEqual(checker.find_conflicts(grid), [(3, 3), (5, 5)])

    def test_no_conflict_for_different_groups(self):
        grid = [[0] * 9 for _ in range(9)]
        grid[0][0] = grid[4][4] = 7            # different row, column and box
        self.assertEqual(checker.find_conflicts(grid), [])

    def test_triple_conflict_flags_all_three(self):
        grid = [[0] * 9 for _ in range(9)]
        grid[0][0] = grid[0][5] = grid[7][0] = 2   # row clash and column clash share (0, 0)
        self.assertEqual(checker.find_conflicts(grid), [(0, 0), (0, 5), (7, 0)])

    def test_box_only_errors_are_caught(self):
        # Every row and column holds 1-9, but the 3x3 boxes repeat numbers.
        grid = [[(r + c) % 9 + 1 for c in range(9)] for r in range(9)]
        for i in range(9):
            self.assertEqual(sorted(grid[i]), list(range(1, 10)))
            self.assertEqual(sorted(grid[r][i] for r in range(9)), list(range(1, 10)))
        self.assertFalse(checker.is_solved(grid))
        self.assertTrue(checker.find_conflicts(grid))

    def test_swapped_cells_break_the_solution(self):
        grid = copy(SOLVED)
        grid[0][0], grid[0][1] = grid[0][1], grid[0][0]   # row still fine, columns break
        self.assertFalse(checker.is_solved(grid))
        self.assertIn((0, 0), checker.find_conflicts(grid))

    def test_generator_candidates_skip_row_column_and_box(self):
        grid = [[0] * 9 for _ in range(9)]
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
        puzzle = INKALA
        self.assertEqual(checker.check_player_board(puzzle, copy(puzzle))["status"], "in_progress")
        self.assertEqual(checker.check_player_board(puzzle, INKALA_SOLUTION)["status"], "solved")

        clash = copy(puzzle)
        clash[0][1] = 8     # player types a second 8 in the first row
        result = checker.check_player_board(puzzle, clash)
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["conflicts"], [(0, 0), (0, 1)])

        changed_clue = copy(INKALA_SOLUTION)
        changed_clue[0][0] = 1  # overwrites the given 8
        self.assertEqual(checker.check_player_board(puzzle, changed_clue)["status"], "invalid")


# 4. Difficulty labels vs. the solving techniques really needed

class TestDifficulty(unittest.TestCase):

    def test_rater_on_reference_puzzles(self):
        # A board with one empty cell needs only a naked single.
        one_gap = copy(SOLVED)
        one_gap[4][4] = 0
        self.assertEqual(rate_by_technique(one_gap), SINGLES)
        self.assertEqual(rate_by_technique(INKALA), ADVANCED)

    def test_fewer_clues_for_harder_levels(self):
        targets = [generator.DIFFICULTY_CLUES[d] for d in DIFFICULTIES]
        self.assertEqual(targets, sorted(targets, reverse=True))

    def test_easy_needs_only_naked_singles(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(rate_by_technique(generated("easy", seed)["puzzle"]), SINGLES)

    def test_harder_labels_need_harder_techniques_on_average(self):
        averages = []
        for difficulty in DIFFICULTIES:
            ratings = [rate_by_technique(generated(difficulty, s)["puzzle"]) for s in SEEDS]
            averages.append(sum(ratings) / len(ratings))
        self.assertEqual(averages, sorted(averages), f"average technique level per label: {averages}")

    def test_expert_is_never_singles_only(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertGreater(rate_by_technique(generated("expert", seed)["puzzle"]), SINGLES)

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
        mismatches = []
        for difficulty in DIFFICULTIES:
            for seed in SEEDS:
                level = rate_by_technique(generated(difficulty, seed)["puzzle"])
                if level not in allowed[difficulty]:
                    mismatches.append(f"{difficulty} seed {seed}: needs {TECHNIQUE_NAMES[level]}")
        self.assertEqual(mismatches, [], "\n" + "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main(verbosity=2)
