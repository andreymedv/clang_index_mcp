#ifndef NAMESPACE_AMBIGUITY_H
#define NAMESPACE_AMBIGUITY_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 47: Same class name in different namespaces with derived classes
// ============================================================================

namespace gui {
struct Widget {
    void guiWidgetMethod() {}
};

struct Button : public Widget {
    void guiButtonMethod() {}
};
}  // namespace gui

namespace data {
struct Widget {
    void dataWidgetMethod() {}
};

struct DataView : public Widget {
    void dataViewMethod() {}
};
}  // namespace data

// ============================================================================
// TEST CASE 48: Class inheriting from ns1::Base where ns2::Base also exists
// ============================================================================

namespace ns1 {
struct Base {
    void ns1BaseMethod() {}
};
}  // namespace ns1

namespace ns2 {
struct Base {
    void ns2BaseMethod() {}
};
}  // namespace ns2

struct InheritsFromNs1 : public ns1::Base {
    void inheritsNs1Method() {}
};

struct InheritsFromNs2 : public ns2::Base {
    void inheritsNs2Method() {}
};

// ============================================================================
// TEST CASE 49: Using-declaration bringing a name into scope, then inheriting
// ============================================================================

namespace source_ns {
struct ImportedBase {
    void importedMethod() {}
};
}  // namespace source_ns

namespace target_ns {
using source_ns::ImportedBase;

struct InheritsImported : public ImportedBase {
    void inheritsImportedMethod() {}
};
}  // namespace target_ns

// ============================================================================
// TEST CASE 50: Nested namespace hierarchy with same leaf names
// ============================================================================

namespace a {
namespace b {
struct Item {
    void abItemMethod() {}
};
}  // namespace b
}  // namespace a

namespace c {
namespace d {
struct Item {
    void cdItemMethod() {}
};
}  // namespace d
}  // namespace c

struct DerivedFromAB : public a::b::Item {
    void derivedABMethod() {}
};

struct DerivedFromCD : public c::d::Item {
    void derivedCDMethod() {}
};

// ============================================================================
// TEST CASE 51: Class in anonymous namespace inheriting from named namespace
// ============================================================================

namespace named {
struct NamedBase {
    void namedMethod() {}
};
}  // namespace named

namespace {
struct AnonDerived : public named::NamedBase {
    void anonMethod() {}
};
}  // anonymous namespace

// ============================================================================
// TEST CASE 52: Template instantiated with classes from different namespaces
// ============================================================================

template <typename T>
class NsWrapper : public T {
public:
    void nsWrapperMethod() {}
};

struct WrappedGuiWidget : public NsWrapper<gui::Widget> {
    void wrappedGuiMethod() {}
};

struct WrappedDataWidget : public NsWrapper<data::Widget> {
    void wrappedDataMethod() {}
};

// ============================================================================
// TEST CASE 53: Qualified vs unqualified base class reference
// ============================================================================

namespace ambig {
struct Base {
    void ambigBaseMethod() {}
};

// Unqualified: refers to ambig::Base (innermost scope)
struct UnqualDerived : public Base {
    void unqualMethod() {}
};
}  // namespace ambig

// Qualified: explicitly references ambig::Base
struct QualDerived : public ambig::Base {
    void qualMethod() {}
};

}  // namespace inheritance_test

#endif  // NAMESPACE_AMBIGUITY_H
