#ifndef NAME_COLLISION_H
#define NAME_COLLISION_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 31: Template parameter named same as concrete struct, used as base
// ============================================================================

struct Base {
    void concreteBaseMethod() {}
};

// Template param "Base" collides with the concrete struct "Base" above
template <typename Base>
class WrapperCollidesWithBase : public Base {
public:
    void wrapperMethod() {}
};

// Real derivation from concrete struct Base
struct RealDerivedFromBase : public Base {
    void realDerivedMethod() {}
};

// Instantiation: this DOES derive from concrete struct Base (through template)
struct InstantiatedWrapper : public WrapperCollidesWithBase<Base> {
    void instantiatedMethod() {}
};

// ============================================================================
// TEST CASE 32: Multiple templates with different colliding parameter names
// ============================================================================

struct Handler {
    void handleMethod() {}
};

struct Processor {
    void processMethod() {}
};

// Template param "Handler" collides with concrete struct "Handler"
template <typename Handler>
class HandlerWrapper : public Handler {
public:
    void handlerWrapperMethod() {}
};

// Template param "Processor" collides with concrete struct "Processor"
template <typename Processor>
class ProcessorWrapper : public Processor {
public:
    void processorWrapperMethod() {}
};

// ============================================================================
// TEST CASE 33: Template param name matches a class in a different namespace
// ============================================================================

namespace other {
struct Widget {
    void otherWidgetMethod() {}
};
}  // namespace other

// Template param "Widget" matches other::Widget
template <typename Widget>
class WidgetAdapter : public Widget {
public:
    void adapterMethod() {}
};

// Concrete derivation from other::Widget
struct ConcreteWidgetChild : public other::Widget {
    void childMethod() {}
};

// ============================================================================
// TEST CASE 34: Nested scope where template param shadows outer class name
// ============================================================================

struct Outer {
    void outerMethod() {}

    // Template param "Outer" shadows the enclosing struct "Outer"
    template <typename Outer>
    class Inner : public Outer {
    public:
        void innerMethod() {}
    };
};

}  // namespace inheritance_test

#endif  // NAME_COLLISION_H
