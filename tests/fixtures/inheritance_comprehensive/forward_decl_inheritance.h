#ifndef FORWARD_DECL_INHERITANCE_H
#define FORWARD_DECL_INHERITANCE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 35: Simple forward declaration followed by definition with base
// ============================================================================

struct FwdBase {
    virtual ~FwdBase() = default;
    void fwdBaseMethod() {}
};

// Forward declaration (no base classes visible)
struct FwdDerived;

// Actual definition (has base class)
struct FwdDerived : public FwdBase {
    void fwdDerivedMethod() {}
};

// ============================================================================
// TEST CASE 36: Forward declaration via macro-like pattern
// ============================================================================

// Simulate macro-generated empty struct (is_definition=true in libclang)
#define DECLARE_WIDGET(name) struct name {};

struct WidgetBase36 {
    virtual ~WidgetBase36() = default;
    void widgetBaseMethod() {}
};

// Macro generates: struct MacroWidget {};  (empty, but is_definition=true)
DECLARE_WIDGET(MacroWidget)

// To have the real definition we need a separate compilation path.
// In practice, the macro-generated empty struct and the real definition
// would come from different translation units. For this fixture,
// we demonstrate the pattern but note that in a single TU, only the
// macro definition (empty) is seen by the compiler.

// ============================================================================
// TEST CASE 37: Multiple forward declarations of same class before definition
// ============================================================================

struct MultiFwdBase {
    void multiFwdBaseMethod() {}
};

// Multiple forward declarations
struct MultiFwdDerived;
struct MultiFwdDerived;
struct MultiFwdDerived;

// Single definition with base class
struct MultiFwdDerived : public MultiFwdBase {
    void multiFwdDerivedMethod() {}
};

}  // namespace inheritance_test

#endif  // FORWARD_DECL_INHERITANCE_H
