# libclang Validation Experiments

**Purpose:** Validate assumptions before qualified name support prioritization

---

## Quick Start

```bash
# 1. Activate environment
cd /path/to/clang_index_mcp
source mcp_env/bin/activate

# 2. Verify libclang works
python scripts/experiments/test_libclang_behavior.py --verify

# 3. Run all tests (~5 minutes)
python scripts/experiments/test_libclang_behavior.py --all

# 4. Document results
cp docs/experiments/LIBCLANG_EXPERIMENT_RESULTS_TEMPLATE.md \
   docs/experiments/LIBCLANG_EXPERIMENT_RESULTS.md

# Edit LIBCLANG_EXPERIMENT_RESULTS.md with your findings
```

---

## Files

- **LIBCLANG_VALIDATION_EXPERIMENT.md** - Detailed experiment guide
- **LIBCLANG_EXPERIMENT_RESULTS_TEMPLATE.md** - Template for recording results
- **../../scripts/experiments/test_libclang_behavior.py** - Automated test script

---

## Critical Test: TC4

The **most important** test is TC4 (Base Class with Alias).

**Quick check:**
```bash
python scripts/experiments/test_libclang_behavior.py --test tc4
```

Look for the **VERDICT** line in output:
- ✅ "Q3 works" → aliases expanded, continue as planned
- ❌ "Q12 blocks Q3" → aliases NOT expanded, adjust priorities

---

## If You Get Stuck

**Parse errors?**
- Check libclang version: `python -c "import clang.cindex; print(clang.cindex.version.__version__)"`
- Try simpler test: `--test tc1`

**Script won't run?**
```bash
# Make executable
chmod +x scripts/experiments/test_libclang_behavior.py

# Check Python has clang module
python -c "import clang.cindex; print('OK')"
```

**Unclear results?**
- Document what you see in LIBCLANG_EXPERIMENT_RESULTS.md
- Share with Claude in next session
- We'll analyze together

---

## Time Estimate

- Setup verification: 5 minutes
- Running all tests: 5 minutes
- Documenting results: 30 minutes
- **Total: ~40 minutes** (faster than estimated 2-3 hours!)

---

## What Happens Next

1. You run experiments and document results
2. Share results with Claude
3. We analyze together (30 minutes)
4. Adjust prioritization based on findings
5. Proceed with implementation planning

Good luck! 🔬
