#!/bin/bash
echo "Running freezing test 10 times to confirm stability..."
PASSED=0
for i in {1..10}; do
  printf "Run %d/10: " $i
  if timeout 30 python3 -m pytest tests/robustness/test_data_integrity.py::TestAtomicCacheWrites::test_concurrent_cache_write_protection -xq > /tmp/run_$i.log 2>&1; then
    TIME=$(grep "1 passed" /tmp/run_$i.log | grep -oP '\d+\.\d+s' || echo "?s")
    echo "✅ PASSED ($TIME)"
    PASSED=$((PASSED + 1))
  elif [ $? -eq 124 ]; then
    echo "❌ TIMEOUT (FREEZE!)"
    cat /tmp/run_$i.log
    exit 1
  else
    echo "❌ FAILED (exit $?)"
    tail -5 /tmp/run_$i.log
  fi
done
echo ""
echo "✅ Result: $PASSED/10 runs passed without freezing!"
