#pragma once

// Fixture for cplusplus_mcp-jqqq: template specializations as first-class
// hierarchy nodes. Variant WITH explicit instantiation definitions (indexed
// full_specialization symbols whose names have template args stripped).

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

template class T<A1>;
template class T<A2>;

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

template class NT<NA>;

} // namespace ns
