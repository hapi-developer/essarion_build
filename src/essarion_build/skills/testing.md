# Testing

- **Test behavior, not implementation.** A test that breaks when you refactor without changing behavior is a bad test. Assert on outputs and observable side-effects, not on which private method got called.
- **Pyramid: many unit, fewer integration, very few end-to-end.** Unit tests catch most regressions cheaply. E2E tests catch what no other layer can but are slow and flaky.
- **One concept per test.** A test named `test_user_signup` that exercises the form, the DB write, the welcome email, and the redirect is four tests in a trench coat — split them.
- **Arrange / Act / Assert.** Blank lines between the three sections make the test scannable.
- **Test the edges.** Empty input, max input, exactly-at-limit, off-by-one. Bugs cluster at boundaries.
- **Don't mock what you don't own.** Mocking your own DB layer is fine; mocking a third-party library's internals couples your tests to that library's version.
- **Failing tests should be diagnostic.** When a test fails, the failure message should say which invariant broke. Prefer `assert response.status_code == 200, response.text` to bare `assert`.
- **Fixtures, not setUp soup.** Pytest fixtures with explicit scopes (`session`, `module`, `function`) beat shared mutable state.
- **Coverage is a floor, not a ceiling.** 100% coverage of trivial getters proves nothing. Aim for branch coverage on the logic that matters.
