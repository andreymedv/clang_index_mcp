# Test Plan: Integration and Test Fixtures

**Part of**: [Comprehensive Test Plan](./TEST_PLAN.md)

This document covers test fixtures, utilities, and integration test requirements.

---

## 9. Test Fixtures Required

### 9.1 Minimal Fixtures (Unit Tests)

```
tests/fixtures/
├── classes/
│   ├── simple_class.h              # class MyClass {};
│   ├── simple_struct.h             # struct MyStruct {};
│   ├── template_class.h            # template<typename T> class Vector {};
│   ├── nested_class.h              # Outer::Inner
│   ├── forward_decl.h              # Forward + full declaration
│   ├── anonymous_struct.h          # struct { int x; };
│   └── abstract_class.h            # Pure virtual methods
├── inheritance/
│   ├── single_inheritance.h        # Derived : Base
│   ├── multiple_inheritance.h      # Derived : Base1, Base2
│   ├── virtual_inheritance.h       # Derived : virtual Base
│   └── deep_hierarchy.h            # GrandChild->Child->Parent->GrandParent
├── functions/
│   ├── global_functions.cpp        # Global functions
│   ├── static_func.cpp             # static void func()
│   ├── inline_func.h               # inline int func()
│   ├── constexpr_func.h            # constexpr int func()
│   ├── template_func.h             # template<typename T> T max()
│   ├── overloads.cpp               # Multiple overloaded()
│   ├── variadic.cpp                # void func(int, ...)
│   ├── operators.cpp               # operator+, operator==
│   └── class_methods.h             # Class with methods
├── methods/
│   ├── regular.h                   # void method()
│   ├── static_method.h             # static void method()
│   ├── const_method.h              # void method() const
│   ├── virtual_method.h            # virtual void method()
│   ├── pure_virtual.h              # virtual void method() = 0
│   ├── override.h                  # void method() override
│   ├── final.h                     # void method() final
│   ├── constructors.h              # Various constructors
│   ├── destructor.h                # ~MyClass()
│   ├── virtual_destructor.h        # virtual ~MyClass()
│   └── operator_methods.h          # Operator overloads as methods
├── templates/
│   ├── class_template.h            # template<typename T> class
│   ├── function_template.h         # template<typename T> T func()
│   ├── specialization.h            # Template specializations
│   └── variadic_template.h         # template<typename... Args>
├── namespaces/
│   ├── named_namespace.h           # namespace MyNamespace {}
│   ├── nested_namespace.h          # namespace Outer::Inner {}
│   └── anonymous_namespace.cpp     # namespace {}
├── call_graph/
│   ├── simple_calls.cpp            # A calls B calls C
│   ├── method_calls.cpp            # obj.method()
│   ├── static_calls.cpp            # Class::staticMethod()
│   ├── virtual_calls.cpp           # Virtual dispatch
│   ├── call_chain.cpp              # Long call chain
│   ├── overloaded_calls.cpp        # Calls to overloaded functions
│   └── complex_calls.cpp           # Multiple call patterns
├── relationships/
│   ├── inheritance_tree.h          # Animal -> Dog, Cat
│   ├── deep_hierarchy.h            # Multi-level inheritance
│   └── class_with_methods.h        # Class with multiple methods
└── files/
    └── multi_symbol_file.h         # Multiple classes/functions in one file
```

### 9.2 Integration Fixtures

```
tests/fixtures/projects/
├── minimal/                        # Minimal valid project
│   ├── main.cpp
│   └── simple.h
├── with_dependencies/              # Project + dependency separation
│   ├── src/
│   │   └── main.cpp
│   ├── vcpkg_installed/
│   │   └── include/
│   │       └── lib.h
│   └── .cpp-analyzer-config.json
├── with_compile_commands/          # Project with compile_commands.json
│   ├── src/
│   │   └── main.cpp
│   └── compile_commands.json
├── large_project/                  # 50+ files for parallel testing
│   └── src/
│       ├── file001.cpp ... file050.cpp
└── real_world/                     # Realistic project structure
    ├── include/
    ├── src/
    ├── third_party/
    └── CMakeLists.txt
```

### 9.3 Test Utilities

```python
# tests/test_utils.py
import json
from unittest import mock
from contextlib import contextmanager

def create_temp_project(num_files=5):
    """Create temporary project with N files"""
    pass

def setup_test_analyzer(fixture_path=None):
    """Setup analyzer with test fixture"""
    pass

def index_fixture(fixture_path):
    """Index a specific fixture file"""
    pass

def temp_compile_commands(data):
    """Create temporary compile_commands.json"""
    pass

@contextmanager
def env_var(name, value):
    """Context manager for environment variables"""
    import os
    old_value = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old_value is None:
            del os.environ[name]
        else:
            os.environ[name] = old_value

def temp_dir():
    """Context manager for temporary directory"""
    pass

def temp_config_file(content):
    """Create temporary config file with content"""
    pass

def temp_project_with_cc():
    """Create temporary project with compile_commands.json"""
    pass

def modify_compile_commands(cc_path):
    """Modify compile_commands.json for testing"""
    pass

def temp_project_structure():
    """Create temp project with subdirectories"""
    pass
```

---

