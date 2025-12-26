#!/bin/bash
# Validation script for Issue #002 fix
set -e

echo "==================================================================="
echo "VALIDATION STEP 1: Run freezing test 5 times"
echo "==================================================================="

FAILED_RUNS=0
for i in {1..5}; do
  echo ""
  echo "--- Run $i/5 ---"

  # Run test with 30 second timeout
  if timeout 30 pytest tests/robustness/test_data_integrity.py::TestAtomicCacheWrites::test_concurrent_cache_write_protection -xvs --tb=short > /tmp/test_run_$i.log 2>&1; then
    echo "✅ Run $i: PASSED"
  else
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 124 ]; then
      echo "❌ Run $i: TIMEOUT (test still freezing!)"
      cat /tmp/test_run_$i.log | tail -20
      exit 1
    else
      echo "⚠️ Run $i: FAILED (exit code $EXIT_CODE, but didn't freeze)"
      FAILED_RUNS=$((FAILED_RUNS + 1))
    fi
  fi
done

echo ""
if [ $FAILED_RUNS -eq 0 ]; then
  echo "✅ STEP 1 SUCCESS: All 5 runs completed without freezing!"
else
  echo "⚠️ STEP 1 PARTIAL: $FAILED_RUNS runs failed, but none froze"
fi

echo ""
echo "==================================================================="
echo "VALIDATION STEP 2: Run all 7 affected tests"
echo "==================================================================="

timeout 120 pytest \
  tests/edge_cases/test_race_conditions.py::TestConcurrentModification::test_concurrent_file_modification \
  tests/robustness/test_data_integrity.py::TestAtomicCacheWrites::test_concurrent_cache_write_protection \
  tests/test_concurrent_queries_during_indexing.py \
  tests/test_tools_during_analysis_progress.py::test_background_indexer_progress_integration \
  -v --tb=short 2>&1 | tee /tmp/affected_tests.log

if [ ${PIPESTATUS[0]} -eq 124 ]; then
  echo "❌ STEP 2 FAILED: Tests timed out (freeze detected)"
  exit 1
elif [ ${PIPESTATUS[0]} -eq 0 ]; then
  echo ""
  echo "✅ STEP 2 SUCCESS: All 7 affected tests passed!"
else
  echo ""
  echo "⚠️ STEP 2 PARTIAL: Some tests failed, but none froze"
fi

echo ""
echo "==================================================================="
echo "VALIDATION STEP 3: Check for fork warnings in full suite"
echo "==================================================================="

# Run full test suite and grep for fork warnings
timeout 600 make test > /tmp/full_test_suite.log 2>&1 || true

FORK_WARNINGS=$(grep -c "use of fork() may lead to deadlocks" /tmp/full_test_suite.log || echo "0")

echo ""
echo "Fork deprecation warnings found: $FORK_WARNINGS"

if [ "$FORK_WARNINGS" -eq 0 ]; then
  echo "✅ STEP 3 SUCCESS: No fork warnings!"
else
  echo "❌ STEP 3 FAILED: Still seeing $FORK_WARNINGS fork warnings"
  echo "Showing first few occurrences:"
  grep -A 2 "use of fork() may lead to deadlocks" /tmp/full_test_suite.log | head -20
fi

echo ""
echo "==================================================================="
echo "VALIDATION SUMMARY"
echo "==================================================================="
echo "Step 1: Freezing test (5 runs) - CHECK ABOVE"
echo "Step 2: All 7 affected tests - CHECK ABOVE"
echo "Step 3: Fork warnings - $FORK_WARNINGS found"
echo ""
echo "Full test suite output saved to: /tmp/full_test_suite.log"
echo "==================================================================="
