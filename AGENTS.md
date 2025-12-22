# Pull Request Review Guidelines for Jules

This document outlines the process and requirements for Jules when reviewing pull requests in this repository.

## Primary Goal

The most important aspect of any review is to ensure consistency across the following four pillars:
1.  **Requirements:** The changes should correctly implement the requirements as described in the pull request description and any referenced documentation in the `docs/` directory.
2.  **Production Code:** The code should be clear, correct, and adhere to the project's existing style.
3.  **Tests:** The changes must be accompanied by new or updated tests that cover the new functionality. Existing tests must continue to pass.
4.  **Documentation:** Any user-facing or internal documentation impacted by the changes must be updated to be accurate and complete.

## Secondary Goal

In addition to the primary goal, the review should also include an analysis of the code for potential bugs. This includes, but is not limited to:
*   Logical errors
*   Unhandled edge cases
*   Potential race conditions
*   Resource leaks
*   Security vulnerabilities

## Process

The pull request review process is as follows:
1.  **Initiation:** The user will initiate a review by providing Jules with a branch name and a pull request description.
2.  **Analysis:** Jules will fetch the branch, identify the changed files, and review them against the primary and secondary goals.
3.  **Testing:** Jules will run the full test suite to check for any regressions.
4.  **Reporting:** Jules will provide a single, comprehensive feedback report.
    - The report will only list found errors, mistakes, or recommended fixes. Change descriptions should not be included.
    - If the review finds no issues, no report will be generated. Instead, Jules will state the approval of the changes directly in the session chat.
5.  **Completion:** After the report is delivered, the review task is considered complete.
