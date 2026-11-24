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

# Clues per difficulty, straight from the generator. A puzzle may have up to
# 2 more if the generator couldn't remove more and keep one solution.
CLUES = server.generator.DIFFICULTY_CLUES
EXTRA_CLUES = 2

# The accounts the fake Supabase knows, from test_users.json (fake, not real logins).
# Most tests use the first one; test_every_test_user_can_log_in uses them all.
with open(os.path.join(HERE, "test_users.json")) as f:
    TEST_USERS = {user["email"]: user["password"] for user in json.load(f)}
TEST_EMAIL, TEST_PASSWORD = next(iter(TEST_USERS.items()))

SUPABASE_URL = re.compile(r"https://[^/]+\.supabase\.co/.*")
WRONG = re.compile(r"\bwrong\b")   # the CSS class Check puts on a wrong cell

# Bits of JavaScript run inside the page. They are written as functions
# (() => ...), not bare expressions, because the site's CSP blocks eval().
BOARD_LOADED = ("document.querySelectorAll('#board input').length === 81"
                " && document.getElementById('message').textContent !== 'Loading...'")
PUZZLE_KEY = ("[...document.querySelectorAll('#board input')]"
              ".map(i => i.classList.contains('given') ? i.value : '0').join('')")


# ----- Fake Supabase: answers the browser's requests instead of supabase.co -----

def fake_user(email):
    return {"id": f"user-{email}", "aud": "authenticated", "role": "authenticated", "email": email,
            "email_confirmed_at": "2026-01-01T00:00:00Z", "app_metadata": {"provider": "email"},
            "user_metadata": {}, "created_at": "2026-01-01T00:00:00Z"}


def fake_session(email):
    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    expires_at = int(time.time()) + 3600
    claims = {"sub": f"user-{email}", "email": email, "role": "authenticated",
              "aud": "authenticated", "exp": expires_at}
    token = f"{encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode(claims)}.fake-signature"
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600,
            "expires_at": expires_at, "refresh_token": "fake-refresh", "user": fake_user(email)}


def error(code, error_code, msg):
    return {"code": code, "error_code": error_code, "msg": msg}


class FakeSupabase:
    def __init__(self):
        self.calls = []      # (method, url, body) of every real request (not CORS preflights)
        self.sessions = {}   # access token -> email of the user it was given to

    def handle(self, route):
        request = route.request
        if request.method == "OPTIONS":            # CORS preflight: just allow it
            return self.reply(route, 200, {})

        body = json.loads(request.post_data or "{}") if request.method == "POST" else {}
        self.calls.append((request.method, request.url, body))
        url, email = request.url, body.get("email")

        if "/auth/v1/token" in url:                # log in
            if email in TEST_USERS and body.get("password") == TEST_USERS[email]:
                session = fake_session(email)
                self.sessions[session["access_token"]] = email
                return self.reply(route, 200, session)
            return self.reply(route, 400, error(400, "invalid_credentials", "Invalid login credentials"))

        if "/auth/v1/signup" in url:               # create account
            if email in TEST_USERS:
                return self.reply(route, 422, error(422, "user_already_exists", "User already registered"))
            # Email confirmation is on: a user comes back, but no session.
            return self.reply(route, 200, {**fake_user(email), "email_confirmed_at": None})

        if "/auth/v1/logout" in url:
            return self.reply(route, 204, None)

        if "/auth/v1/user" in url:                 # "who is logged in?"
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if token in self.sessions:
                return self.reply(route, 200, fake_user(self.sessions[token]))
            return self.reply(route, 401, error(401, "bad_jwt", "invalid JWT"))

        return self.reply(route, 404, {"msg": f"fake Supabase: unexpected {url}"})

    @staticmethod
    def reply(route, status, data):
        route.fulfill(status=status, content_type="application/json",
                      body="" if data is None else json.dumps(data),
                      headers={"Access-Control-Allow-Origin": "*",
                               "Access-Control-Allow-Headers": "*",
                               "Access-Control-Allow-Methods": "*"})


# ----- Shared setup: run the website on a free port and open a browser -----

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
        # A fresh browser context per test = no cookies or saved logins carry over.
        self.supabase = FakeSupabase()
        self.context = self.browser.new_context()
        self.context.route(SUPABASE_URL, self.supabase.handle)
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

        self.errors = []    # JavaScript errors on the page
        self.dialogs = []   # alert()/confirm() messages (accepted automatically)
        self.page.on("pageerror", lambda err: self.errors.append(str(err)))
        self.page.on("dialog", self.accept_dialog)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "JavaScript errors on the page")

    def accept_dialog(self, dialog):
        self.dialogs.append(dialog.message)
        dialog.accept()

    # ----- the game page -----

    def open_game(self):
        self.page.goto(self.base + "/")
        self.wait_for_board()

    def wait_for_board(self):
        self.page.wait_for_function(f"() => {BOARD_LOADED}")

    def click(self, button):
        self.page.get_by_role("button", name=button).click()

    def message(self):
        return self.page.locator("#message")

    def cells(self):
        return self.page.locator("#board input")

    def cell(self, r, c):
        return self.page.locator(f'#board input[data-r="{r}"][data-c="{c}"]')

    def wrong_cells(self):
        return self.page.locator("#board input.wrong")

    def board_state(self):
        """List of {r, c, value, given} for all 81 cells, read from the page."""
        return self.page.evaluate("""() => [...document.querySelectorAll('#board input')].map(i => (
            {r: +i.dataset.r, c: +i.dataset.c, value: i.value, given: i.classList.contains('given')}))""")

    def empty_cells(self):
        return [(s["r"], s["c"]) for s in self.board_state() if not s["given"]]

    def given_count(self):
        return sum(s["given"] for s in self.board_state())

    def puzzle_key(self):
        """The clues as an 81-character string ('0' = empty), to tell puzzles apart."""
        return self.page.evaluate(f"() => {PUZZLE_KEY}")

    def solution(self):
        return self.page.evaluate("() => solution")   # the page keeps it in a global variable

    def right_digit(self, r, c):
        return str(self.solution()[r][c])

    def wrong_digit(self, r, c):
        return str(self.solution()[r][c] % 9 + 1)   # any digit that isn't the right one

    def fill_correctly(self, cells):
        solution = self.solution()
        for r, c in cells:
            self.cell(r, c).fill(str(solution[r][c]))

    def new_game(self, difficulty):
        """Pick a difficulty, press New Game and wait until a different puzzle shows."""
        before = self.puzzle_key()
        self.page.select_option("#difficulty", difficulty)
        self.click("New Game")
        self.page.wait_for_function(f"before => {BOARD_LOADED} && {PUZZLE_KEY} !== before", arg=before)

    # ----- the login page -----

    def open_login(self):
        self.page.goto(self.base + "/login")
        expect(self.page.get_by_role("heading", name="Log In")).to_be_visible()

    def fill_login(self, email, password):
        self.page.fill("#email", email)
        self.page.fill("#password", password)

    def log_in(self, email=TEST_EMAIL, password=TEST_PASSWORD):
        self.open_login()
        self.fill_login(email, password)
        self.click("Log In")
        expect(self.page).to_have_url(self.base + "/")


# 1. Grid & input rules

class TestGridAndInput(SudokuE2E):

    def setUp(self):
        super().setUp()
        self.open_game()
        r, c = self.empty_cells()[0]
        self.empty = self.cell(r, c)        # an empty cell to type into
        self.clues = self.page.locator("#board input.given")

    def test_board_has_81_cells(self):
        expect(self.cells()).to_have_count(81)

    def test_clue_cells_are_gray_and_read_only(self):
        self.assertGreater(self.clues.count(), 0)
        for clue in self.clues.all():
            expect(clue).to_have_attribute("readonly", "")
        background = self.clues.first.evaluate("e => getComputedStyle(e).backgroundColor")
        self.assertEqual(background, "rgb(240, 240, 240)")

    def test_clue_cells_cannot_be_overwritten(self):
        clue = self.clues.first
        original = clue.input_value()
        clue.click()
        self.page.keyboard.press("Backspace")
        self.page.keyboard.type("9")
        expect(clue).to_have_value(original)

    def test_empty_cells_accept_digits_1_to_9(self):
        for digit in "123456789":
            self.empty.fill("")
            self.empty.press_sequentially(digit)
            expect(self.empty).to_have_value(digit)

    def test_empty_cells_reject_zero_letters_and_symbols(self):
        for key in ["0", "a", "Z", "#", "-", " ", ".", "é"]:
            with self.subTest(key=key):
                self.empty.fill("")
                self.empty.press_sequentially(key)
                expect(self.empty).to_have_value("")

    def test_empty_cell_holds_only_one_digit(self):
        self.empty.press_sequentially("57")
        expect(self.empty).to_have_value("5")


# 2. "Check" button logic

class TestCheckButton(SudokuE2E):

    def setUp(self):
        super().setUp()
        self.open_game()
        self.empties = self.empty_cells()

    def test_check_on_empty_board_does_not_crash(self):
        self.click("Check")
        expect(self.message()).to_have_text(f"No mistakes so far. {len(self.empties)} cells left.")

    def test_wrong_entry_is_flagged_red(self):
        r, c = self.empties[0]
        self.cell(r, c).fill(self.wrong_digit(r, c))
        self.click("Check")
        expect(self.cell(r, c)).to_have_class(WRONG)
        expect(self.message()).to_have_text("1 mistake(s) shown in red.")

    def test_correct_entries_are_not_flagged(self):
        self.fill_correctly(self.empties[:5])
        self.click("Check")
        expect(self.wrong_cells()).to_have_count(0)
        expect(self.message()).to_have_text(f"No mistakes so far. {len(self.empties) - 5} cells left.")

    def test_counts_several_mistakes(self):
        for r, c in self.empties[:3]:
            self.cell(r, c).fill(self.wrong_digit(r, c))
        self.click("Check")
        expect(self.wrong_cells()).to_have_count(3)
        expect(self.message()).to_have_text("3 mistake(s) shown in red.")

    def test_fixing_a_mistake_clears_the_red(self):
        r, c = self.empties[0]
        box = self.cell(r, c)
        box.fill(self.wrong_digit(r, c))
        self.click("Check")
        expect(box).to_have_class(WRONG)

        box.fill("")
        box.press_sequentially(self.right_digit(r, c))
        expect(box).not_to_have_class(WRONG)
        self.click("Check")
        expect(self.wrong_cells()).to_have_count(0)

    def test_full_correct_board_shows_win(self):
        self.fill_correctly(self.empties)
        self.click("Check")
        expect(self.message()).to_contain_text("Solved! Well done!")
        expect(self.wrong_cells()).to_have_count(0)

    def test_full_board_with_one_mistake_is_not_a_win(self):
        self.fill_correctly(self.empties)
        r, c = self.empties[0]
        self.cell(r, c).fill(self.wrong_digit(r, c))
        self.click("Check")
        expect(self.message()).to_have_text("1 mistake(s) shown in red.")
        expect(self.message()).not_to_contain_text("Solved")


# 3. Difficulty & "New Game" flow

class TestNewGame(SudokuE2E):

    def setUp(self):
        super().setUp()
        self.open_game()

    def assert_clue_count(self, difficulty):
        self.assertTrue(CLUES[difficulty] <= self.given_count() <= CLUES[difficulty] + EXTRA_CLUES,
                        f"{self.given_count()} clues on {difficulty}")

    def test_default_difficulty_is_medium(self):
        expect(self.page.locator("#difficulty")).to_have_value("medium")
        self.assert_clue_count("medium")

    def test_each_difficulty_has_the_right_number_of_clues(self):
        for difficulty in CLUES:
            with self.subTest(difficulty=difficulty):
                self.new_game(difficulty)
                self.assert_clue_count(difficulty)

    def test_new_game_gives_a_fresh_board(self):
        first = self.puzzle_key()
        self.new_game("medium")
        self.assertNotEqual(self.puzzle_key(), first)

    def test_new_game_clears_entries_and_marks(self):
        r, c = self.empty_cells()[0]
        self.cell(r, c).fill(self.wrong_digit(r, c))
        self.click("Check")
        self.new_game("easy")
        expect(self.wrong_cells()).to_have_count(0)
        expect(self.message()).to_have_text("")
        self.assertTrue(all(s["value"] == "" for s in self.board_state() if not s["given"]))

    @unittest.expectedFailure
    def test_warns_before_wiping_a_game_in_progress(self):
        """KNOWN GAP: New Game replaces the board straight away without asking.
        Remove @expectedFailure once the page asks before wiping entries."""
        r, c = self.empty_cells()[0]
        self.cell(r, c).fill("5")
        self.click("New Game")
        self.page.wait_for_timeout(500)
        warning_on_page = self.page.get_by_text(re.compile("lose|progress|sure", re.I)).count() > 0
        self.assertTrue(self.dialogs or warning_on_page,
                        "no warning before the game in progress was replaced")


# 4. Authentication & session state

class TestAuthentication(SudokuE2E):

    def assert_message(self, text, css_class):
        expect(self.message()).to_have_text(text)
        expect(self.message()).to_have_class(css_class)

    def assert_logged_in(self, email=TEST_EMAIL):
        expect(self.page.locator("#account")).to_contain_text(f"Logged in as {email}")

    def assert_nothing_sent_to_supabase(self):
        self.assertEqual(self.supabase.calls, [], "the form was sent to Supabase")

    def test_log_in_link_and_back_to_sudoku(self):
        self.open_game()
        self.page.get_by_role("link", name="Log In").click()
        expect(self.page).to_have_url(self.base + "/login")
        self.page.get_by_role("link", name="Back to Sudoku").click()
        expect(self.page).to_have_url(self.base + "/")
        self.wait_for_board()

    def test_invalid_email_format_is_blocked(self):
        self.open_login()
        for email in ["not-an-email", "missing-at.com", "user@", "@example.com"]:
            with self.subTest(email=email):
                self.fill_login(email, TEST_PASSWORD)
                self.click("Log In")
                self.assertFalse(self.page.locator("#email").evaluate("e => e.checkValidity()"))
                expect(self.page).to_have_url(self.base + "/login")
        self.assert_nothing_sent_to_supabase()

    def test_empty_fields_are_blocked(self):
        self.open_login()
        self.click("Log In")
        self.click("Create account")
        self.assert_nothing_sent_to_supabase()

    def test_short_password_is_blocked(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, "12345")
        self.click("Create account")
        self.assertFalse(self.page.locator("#password").evaluate("e => e.checkValidity()"))
        self.assert_nothing_sent_to_supabase()

    def test_wrong_password_shows_error(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, "wrong-password")
        self.click("Log In")
        self.assert_message("Invalid login credentials", "error")
        expect(self.page).to_have_url(self.base + "/login")
        expect(self.page.get_by_role("button", name="Log In")).to_be_enabled()

    def test_correct_login_returns_to_game_logged_in(self):
        self.log_in()
        self.assert_logged_in()
        self.wait_for_board()

    def test_every_test_user_can_log_in(self):
        self.assertEqual(len(TEST_USERS), 100)
        for email, password in TEST_USERS.items():
            with self.subTest(email=email):
                self.log_in(email, password)
                self.assert_logged_in(email)
                self.page.evaluate("() => localStorage.clear()")   # forget them before the next user

    def test_users_cannot_use_each_others_passwords(self):
        first_email = list(TEST_USERS)[0]
        second_password = list(TEST_USERS.values())[1]
        self.open_login()
        self.fill_login(first_email, second_password)
        self.click("Log In")
        self.assert_message("Invalid login credentials", "error")

    def test_log_out(self):
        self.log_in()
        self.assert_logged_in()
        self.page.get_by_role("link", name="Log out").click()
        expect(self.page.get_by_role("link", name="Log In")).to_be_visible()
        expect(self.page.locator("#account")).not_to_contain_text("Logged in")

    def test_login_survives_page_reload(self):
        self.log_in()
        self.assert_logged_in()
        self.page.reload()
        self.assert_logged_in()

    def test_create_account_asks_to_confirm_email(self):
        self.open_login()
        self.fill_login("new.user@example.com", "new-password")
        self.click("Create account")
        self.assert_message("Account created. Check your email to confirm it, then log in.", "success")

    def test_create_account_with_existing_email(self):
        self.open_login()
        self.fill_login(TEST_EMAIL, TEST_PASSWORD)
        self.click("Create account")
        self.assert_message("User already registered", "error")

    def test_password_is_sent_only_to_supabase(self):
        sent_to = []   # every address the password was sent to

        def watch(request):
            if TEST_PASSWORD in (request.post_data or ""):
                sent_to.append(request.url)

        self.page.on("request", watch)
        self.log_in()
        self.assertTrue(sent_to, "the password was never sent")
        for url in sent_to:
            self.assertRegex(url, r"^https://[^/]+\.supabase\.co/auth/v1/token")

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
