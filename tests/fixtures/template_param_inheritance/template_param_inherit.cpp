// Test fixture for template parameter inheritance
// Issue cplusplus_mcp-hnj

namespace ns {

// Base class - we'll search for derived classes of this
struct BaseClass {
    void baseMethod() {}
};

// Another base for testing multiple inheritance
struct AnotherBase {
    void anotherMethod() {}
};

// Template that inherits from its template parameter T
template <typename T>
class TemplateInheritsParam : public T {
public:
    void templateMethod() {}
};

// Template with multiple bases, one being template param
template <typename T>
class TemplateMultipleBases : public T, public AnotherBase {
public:
    void multiMethod() {}
};

// Concrete class that inherits from template instantiation
// This INDIRECTLY inherits from BaseClass through TemplateInheritsParam<BaseClass>
struct DerivedFromTemplate : TemplateInheritsParam<BaseClass> {
    void derivedMethod() {}
};

// Another concrete class using the multi-base template
struct DerivedFromTemplateMulti : TemplateMultipleBases<BaseClass> {
    void derivedMultiMethod() {}
};

// Direct inheritance for comparison
struct DirectDerived : BaseClass {
    void directMethod() {}
};

// No inheritance from BaseClass
struct Unrelated {
    void unrelatedMethod() {}
};

// Concrete struct named "Base" - same name as a common template parameter
// Issue cplusplus_mcp-hff: template param names must not cause false positives
struct Base {
    void baseMethod() {}
};

// Template with param name "Base" that collides with the concrete struct above
template <typename Base>
class Adapter : public Base {
public:
    void adapterMethod() {}
};

// Concrete class that actually derives from the struct Base (direct inheritance)
struct RealDerivedFromBase : Base {
    void realDerivedMethod() {}
};

} // namespace ns

// Force instantiation to ensure templates are visible
void force_instantiation() {
    ns::DerivedFromTemplate d1;
    ns::DerivedFromTemplateMulti d2;
    ns::DirectDerived d3;
    ns::Unrelated u;
    ns::RealDerivedFromBase rdfb;
}
