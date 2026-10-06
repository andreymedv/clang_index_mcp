#pragma once

// Fixture for cplusplus_mcp-jqqq: template specializations as first-class
// hierarchy nodes. Variant WITHOUT explicit instantiation definitions — no
// specialization symbols are indexed, so T<A1>/T<A2> nodes must be synthesized
// on the fly from base_classes strings.

class A1 {
public:
    virtual void foo() = 0;
    virtual ~A1() = default;
};

class A2 {
public:
    virtual void bar() = 0;
    virtual ~A2() = default;
};

template <typename P>
class T : public P {
public:
    void common() {}
};

class D1 : public T<A1> {
public:
    void foo() override {}
};

class D2 : public T<A2> {
public:
    void bar() override {}
};

// Namespaced analogue: keys must carry qualified template arguments.
namespace ns {

class NA {
public:
    virtual void na() = 0;
    virtual ~NA() = default;
};

template <typename P>
class NT : public P {
public:
    void ncommon() {}
};

class ND : public NT<NA> {
public:
    void na() override {}
};

} // namespace ns
