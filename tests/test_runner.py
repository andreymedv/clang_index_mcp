#!/usr/bin/env python3
"""
Test runner for compile_commands.json integration tests.

This script runs all the tests and provides a summary of the results.
"""

import unittest
import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def run_tests():
    """Run all tests and return the result."""
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = str(Path(__file__).parent)
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    
    return result.wasSuccessful()

def main():
    """Main function to run tests."""
    print("=" * 60)
    print("Running Compile Commands Integration Tests")
    print("=" * 60)
    
    try:
        success = run_tests()
        
        print("\n" + "=" * 60)
        if success:
            print("✅ All tests passed!")
            sys.exit(0)
        else:
            print("❌ Some tests failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()