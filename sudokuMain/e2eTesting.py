"""
End-to-end (E2E) tests for the Sudoku website.

They open the real pages in a real browser (Chromium, via Playwright), click
and type like a player would, and check what appears on screen.

Supabase is replaced by a fake inside the browser, so the tests never create
real accounts or touch your Supabase project, and they work offline.

Setup (once, from the project folder):
    python3 -m venv .venv
    .venv/bin/pip install playwright
    .venv/bin/python -m playwright install chromium

Run:
    .venv/bin/python sudokuMain/e2eTesting.py
    HEADED=1 .venv/bin/python sudokuMain/e2eTesting.py     # watch the browser
"""

import base64
import json
import os
import re
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright, expect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "Web"))
import server  # noqa: E402  (Web/server.py - its Handler serves the real site)

CLUE_TARGETS = {"easy": 40, "medium": 32, "hard": 27, "expert": 23}

# The fake Supabase knows exactly one account.
TEST_EMAIL = "player@example.com"
TEST_PASSWORD = "correct-password"


# Fake Supabase Auth (answers the browser's requests instead of supabase.co)

def _fake_jwt(email):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    claims = {"sub": "user-1", "email": email, "role": "authenticated",
              "aud": "authenticated", "exp": int(time.time()) + 3600}
    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(claims)}.fake-signature"


def _fake_user(email):
    return {"id": "user-1", "aud": "authenticated", "role": "authenticated", "email": email,
            "email_confirmed_at": "2026-01-01T00:00:00Z", "app_metadata": {"provider": "email"},
            "user_metadata": {}, "created_at": "2026-01-01T00:00:00Z"}


class FakeSupabase:
    def __init__(self):
        self.requests = []   # every request the page sent to Supabase

    def handle(self, route):
        request = route.request
        body = json.loads(request.post_data or "{}") if request.method == "POST" else {}
        self.requests.append((request.method, request.url, body))
        url = request.url

        if "/auth/v1/token" in url:
            if body.get("email") == TEST_EMAIL and body.get("password") == TEST_PASSWORD:
                return self._json(route, 200, {
                    "access_token": _fake_jwt(TEST_EMAIL), "token_type": "bearer",
                    "expires_in": 3600, "expires_at": int(time.time()) + 3600,
                    "refresh_token": "fake-refresh", "user": _fake_user(TEST_EMAIL)})
            return self._json(route, 400, {"code": 400, "error_code": "invalid_credentials",
                                           "msg": "Invalid login credentials"})

        if "/auth/v1/signup" in url:
            if body.get("email") == TEST_EMAIL:
                return self._json(route, 422, {"code": 422, "error_code": "user_already_exists",
                                               "msg": "User already registered"})
            # Email confirmation is on: a user comes back, but no session.
            return self._json(route, 200, {**_fake_user(body.get("email")), "email_confirmed_at": None})

        if "/auth/v1/logout" in url:
            return route.fulfill(status=204, body="")

        if "/auth/v1/user" in url:
            return self._json(route, 200, _fake_user(TEST_EMAIL))

        return self._json(route, 404, {"msg": f"fake Supabase: unexpected {url}"})

    @staticmethod
    def _json(route, status, data):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data),
                      headers={"Access-Control-Allow-Origin": "*"})

    def auth_calls(self):
        return [r for r in self.requests if r[0] != "OPTIONS"]


# Shared setup: start the website on a free port and open a browser

class QuietHandler(server.Handler):
    """The real site handler, without printing every request during tests."""
    def log_message(self, *args):
        pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # the browser closing a connection early is normal during tests


class SudokuE2E(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = QuietServer(("127.0.0.1", 0), QuietHandler)  # port 0 = any free port
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=not os.environ.get("HEADED"))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()

    def setUp(self):
        self.supabase = FakeSupabase()
        self.context = self.browser.new_context()
        self.context.route(re.compile(r"https://[^/]+\.supabase\.co/.*"), self.supabase.handle)
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.dialogs = []
        self.page.on("dialog", self._on_dialog)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "JavaScript errors on the page")

    def _on_dialog(self, dialog):
        self.dialogs.append(dialog.message)
        dialog.accept()

    # ----- helpers -----

    def open_game(self):
        self.page.goto(self.base + "/")
        self.wait_for_board()

    def wait_for_board(self):
        # Written as functions, not bare expressions: the site's CSP blocks eval().
        self.page.wait_for_function(
            "() => document.querySelectorAll('#board input').length === 81"
            " && document.getElementById('message').textContent !== 'Loading...'")

    def cells(self):
        return self.page.locator("#board input")

    def cell(self, r, c):
        return self.page.locator(f'#board input[data-r="{r}"][data-c="{c}"]')

    def board_state(self):
        """List of {r, c, value, given} for all 81 cells, read from the page."""
        return self.page.evaluate("""[...document.querySelectorAll('#board input')].map(i => (
            {r: +i.dataset.r, c: +i.dataset.c, value: i.value, given: i.classList.contains('given')}))""")

    def solution(self):
        return self.page.evaluate("() => solution")   # the page keeps it in a global variable

    def empty_cells(self):
        return [(s["r"], s["c"]) for s in self.board_state() if not s["given"]]

    def given_count(self):
        return sum(1 for s in self.board_state() if s["given"])

    def puzzle_key(self):
        return "".join(s["value"] if s["given"] else "0" for s in self.board_state())

    def new_game(self, difficulty):
        before = self.puzzle_key()
        self.page.select_option("#difficulty", difficulty)
        self.page.get_by_role("button", name="New Game").click()
        self.page.wait_for_function(
            "before => document.getElementById('message').textContent !== 'Loading...'"
            " && [...document.querySelectorAll('#board input')].map(i =>"
            " i.classList.contains('given') ? i.value : '0').join('') !== before", arg=before)

    def message(self):
        return self.page.locator("#message")

    def wrong_digit(self, r, c):
        right = self.solution()[r][c]
        return str(right % 9 + 1)   # any digit that isn't the right one


# 1. Grid & input rules

class TestGridAndInput(SudokuE2E):

    def test_board_has_81_cells(self):
        self.open_game()
        expect(self.cells()).to_have_count(81)

    def test_clue_cells_are_gray_and_read_only(self):
        self.open_game()
        givens = self.page.locator("#board input.given")
        self.assertGreater(givens.count(), 0)
        for i in range(givens.count()):
            expect(givens.nth(i)).to_have_attribute("readonly", "")
        first = givens.first
        self.assertEqual(first.evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(240, 240, 240)")

    def test_clue_cells_cannot_be_overwritten(self):
        self.open_game()
        clue = self.page.locator("#board input.given").first
        original = clue.input_value()
        clue.click()
        self.page.keyboard.press("Backspace")
        self.page.keyboard.type("9")
        expect(clue).to_have_value(original)

    def test_empty_cells_accept_digits_1_to_9(self):
        self.open_game()
        r, c = self.empty_cells()[0]
        box = self.cell(r, c)
        for digit in "123456789":
            box.fill("")
            box.press_sequentially(digit)
            expect(box).to_have_value(digit)

    def test_empty_cells_reject_zero_letters_and_symbols(self):
        self.open_game()
        r, c = self.empty_cells()[0]
        box = self.cell(r, c)
        for bad in ["0", "a", "Z", "#", "-", " ", ".", "é"]:
            with self.subTest(key=bad):
                box.fill("")
                box.press_sequentially(bad)
                expect(box).to_have_value("")

    def test_empty_cell_holds_only_one_digit(self):
        self.open_game()
        r, c = self.empty_cells()[0]
        box = self.cell(r, c)
        box.press_sequentially("57")
        expect(box).to_have_value("5")


# 2. "Check" button logic

class TestCheckButton(SudokuE2E):

    def check(self):
        self.page.get_by_role("button", name="Check").click()

    def test_check_on_empty_board_does_not_crash(self):
        self.open_game()
        left = len(self.empty_cells())
        self.check()
        expect(self.message()).to_have_text(f"No mistakes so far. {left} cells left.")

    def test_wrong_entry_is_flagged_red(self):
        self.open_game()
        r, c = self.empty_cells()[0]
        self.cell(r, c).fill(self.wrong_digit(r, c))
        self.check()
        expect(self.cell(r, c)).to_have_class(re.compile(r"\bwrong\b"))
        expect(self.message()).to_have_text("1 mistake(s) shown in red.")

    def test_correct_entries_are_not_flagged(self):
        self.open_game()
        solution = self.solution()
        empties = self.empty_cells()
        for r, c in empties[:5]:
            self.cell(r, c).fill(str(solution[r][c]))
        self.check()
        expect(self.page.locator("#board input.wrong")).to_have_count(0)
        expect(self.message()).to_have_text(f"No mistakes so far. {len(empties) - 5} cells left.")

    def test_counts_several_mistakes(self):
        self.open_game()
        for r, c in self.empty_cells()[:3]:
            self.cell(r, c).fill(self.wrong_digit(r, c))
        self.check()
        expect(self.page.locator("#board input.wrong")).to_have_count(3)
        expect(self.message()).to_have_text("3 mistake(s) shown in red.")

    def test_fixing_a_mistake_clears_the_red(self):
        self.open_game()
        r, c = self.empty_cells()[0]
        box = self.cell(r, c)
        box.fill(self.wrong_digit(r, c))
        self.check()
        expect(box).to_have_class(re.compile(r"\bwrong\b"))
        box.fill("")
        box.press_sequentially(str(self.solution()[r][c]))
        expect(box).not_to_have_class(re.compile(r"\bwrong\b"))
        self.check()
        expect(self.page.locator("#board input.wrong")).to_have_count(0)

    def test_full_correct_board_shows_win(self):
        self.open_game()
        solution = self.solution()
        for r, c in self.empty_cells():
            self.cell(r, c).fill(str(solution[r][c]))
        self.check()
        expect(self.message()).to_contain_text("Solved! Well done!")
        expect(self.page.locator("#board input.wrong")).to_have_count(0)

    def test_full_board_with_one_mistake_is_not_a_win(self):
        self.open_game()
        solution = self.solution()
        empties = self.empty_cells()
        for r, c in empties:
            self.cell(r, c).fill(str(solution[r][c]))
        r, c = empties[0]
        self.cell(r, c).fill(self.wrong_digit(r, c))
        self.check()
        expect(self.message()).to_have_text("1 mistake(s) shown in red.")
        expect(self.message()).not_to_contain_text("Solved")


# 3. Difficulty & "New Game" flow

class TestNewGame(SudokuE2E):

    def test_default_difficulty_is_medium(self):
        self.open_game()
        expect(self.page.locator("#difficulty")).to_have_value("medium")
        self.assertTrue(CLUE_TARGETS["medium"] <= self.given_count() <= CLUE_TARGETS["medium"] + 2)

    def test_each_difficulty_has_the_right_number_of_clues(self):
        self.open_game()
        for difficulty, target in CLUE_TARGETS.items():
            with self.subTest(difficulty=difficulty):
                self.new_game(difficulty)
                clues = self.given_count()
                self.assertGreaterEqual(clues, target)
                self.assertLessEqual(clues, target + 2)

    def test_new_game_gives_a_fresh_board(self):
        self.open_game()
        first = self.puzzle_key()
        self.new_game("medium")
        self.assertNotEqual(self.puzzle_key(), first)

    def test_new_game_clears_entries_and_marks(self):
        self.open_game()
        r, c = self.empty_cells()[0]
        self.cell(r, c).fill(self.wrong_digit(r, c))
        self.page.get_by_role("button", name="Check").click()
        self.new_game("easy")
        expect(self.page.locator("#board input.wrong")).to_have_count(0)
        expect(self.message()).to_have_text("")
        self.assertTrue(all(s["value"] == "" for s in self.board_state() if not s["given"]))

    @unittest.expectedFailure
    def test_warns_before_wiping_a_game_in_progress(self):
        """KNOWN GAP: New Game replaces the board straight away without asking.
        Remove @expectedFailure once the page asks before wiping entries."""
        self.open_game()
        r, c = self.empty_cells()[0]
        self.cell(r, c).fill("5")
        self.page.get_by_role("button", name="New Game").click()
        self.page.wait_for_timeout(500)
        warned = bool(self.dialogs) or self.page.get_by_text(re.compile("lose|progress|sure", re.I)).count() > 0
        self.assertTrue(warned, "no warning before the game in progress was replaced")


# 4. Authentication & session state

class TestAuthentication(SudokuE2E):

    def open_login(self):
        self.page.goto(self.base + "/login")
        expect(self.page.get_by_role("heading", name="Log In")).to_be_visible()

    def fill_login(self, email, password):
        self.page.fill("#email", email)
        self.page.fill("#password", password)

    def login_message(self):
        return self.page.locator("#message")

    def test_log_in_link_and_back_to_sudoku(self):
        self.open_game()
        self.page.get_by_role("link", name="Log In").click()
        expect(self.page).to_have_url(self.base + "/login")
        self.page.get_by_role("link", name="Back to Sudoku").click()
        expect(self.page).to_have_url(self.base + "/")
        self.wait_for_board()

    def test_invalid_email_format_is_blocked(self):
        self.open_login()
        for bad in ["not-an-email", "missing-at.com", "user@", "@example.com"]:
            with self.subTest(email=bad):
                self.fill_login(bad, TEST_PASSWORD)
                self.page.get_by_role("button", name="Log In").click()
                self.assertFalse(self.page.locator("#email").evaluate("e => e.checkValidity()"))
                expect(self.page).to_have_url(self.base + "/login")
        self.assertEqual(self.supabase.auth_calls(), [], "invalid email was sent to Supabase")

    def test_empty_fields_are_blocked(self):
        self.open_login()
        self.page.get_by_role("button", name="Log In").click()
        self.page.get_by_role("button", name="Create account").click()
        self.assertEqual(self.supabase.auth_calls(), [])

    def test_short_password_is_blocked(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, "12345")
        self.page.get_by_role("button", name="Create account").click()
        self.assertFalse(self.page.locator("#password").evaluate("e => e.checkValidity()"))
        self.assertEqual(self.supabase.auth_calls(), [])

    def test_wrong_password_shows_error(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, "wrong-password")
        self.page.get_by_role("button", name="Log In").click()
        expect(self.login_message()).to_have_text("Invalid login credentials")
        expect(self.login_message()).to_have_class("error")
        expect(self.page).to_have_url(self.base + "/login")
        expect(self.page.get_by_role("button", name="Log In")).to_be_enabled()

    def test_correct_login_returns_to_game_logged_in(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, TEST_PASSWORD)
        self.page.get_by_role("button", name="Log In").click()
        expect(self.page).to_have_url(self.base + "/")
        expect(self.page.locator("#account")).to_contain_text(f"Logged in as {TEST_EMAIL}")
        self.wait_for_board()

    def test_log_out(self):
        self.test_correct_login_returns_to_game_logged_in()
        self.page.get_by_role("link", name="Log out").click()
        expect(self.page.get_by_role("link", name="Log In")).to_be_visible()
        expect(self.page.locator("#account")).not_to_contain_text("Logged in")

    def test_login_survives_page_reload(self):
        self.test_correct_login_returns_to_game_logged_in()
        self.page.reload()
        expect(self.page.locator("#account")).to_contain_text(f"Logged in as {TEST_EMAIL}")

    def test_create_account_asks_to_confirm_email(self):
        self.open_login()
        self.fill_login("new.player@example.com", "new-password")
        self.page.get_by_role("button", name="Create account").click()
        expect(self.login_message()).to_have_text("Account created. Check your email to confirm it, then log in.")
        expect(self.login_message()).to_have_class("success")

    def test_create_account_with_existing_email(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, TEST_PASSWORD)
        self.page.get_by_role("button", name="Create account").click()
        expect(self.login_message()).to_have_text("User already registered")
        expect(self.login_message()).to_have_class("error")

    def test_password_is_sent_only_to_supabase(self):
        self.open_login()
        sent_to = []
        self.page.on("request", lambda req: sent_to.append(req.url)
                     if TEST_PASSWORD in (req.post_data or "") else None)
        self.fill_login(TEST_EMAIL, TEST_PASSWORD)
        self.page.get_by_role("button", name="Log In").click()
        expect(self.page).to_have_url(self.base + "/")
        self.assertTrue(sent_to)
        self.assertTrue(all(re.match(r"https://[^/]+\.supabase\.co/auth/v1/token", u) for u in sent_to), sent_to)

    @unittest.expectedFailure
    def test_board_is_kept_after_visiting_login(self):
        """KNOWN GAP: index.html makes a new puzzle on every page load, so going
        to Log In and back loses the current board. Remove @expectedFailure once
        the board is saved (e.g. in localStorage) and restored."""
        self.open_game()
        r, c = self.empty_cells()[0]
        self.cell(r, c).fill("5")
        puzzle = self.puzzle_key()
        self.page.get_by_role("link", name="Log In").click()
        self.page.get_by_role("link", name="Back to Sudoku").click()
        self.wait_for_board()
        self.assertEqual(self.puzzle_key(), puzzle, "the puzzle changed")
        expect(self.cell(r, c)).to_have_value("5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
