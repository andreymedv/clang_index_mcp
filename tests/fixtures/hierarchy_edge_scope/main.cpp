// Fixture for cplusplus_mcp-2601: full base/derived lists on every hierarchy
// node leak sibling MI branches into the result graph.
//
// B1/B2/D/E reproduce the issue's minimal repro (D : B1, B2; E : B1).
// C1/C2/M exercise a node genuinely reached via several bases that are all
// inside the traversal (M : C1, C2; both C1 and C2 derive from B1).

class B1 {
public:
    virtual void f1() = 0;
    virtual ~B1() = default;
};
class B2 {
public:
    virtual void f2() = 0;
    virtual ~B2() = default;
};
class D : public B1, public B2 {
public:
    void f1() override {}
    void f2() override {}
};
class E : public B1 {
public:
    void f1() override {}
};
class C1 : public B1 {
public:
    void f1() override {}
};
class C2 : public B1 {
public:
    void f1() override {}
};
class M : public C1, public C2 {
public:
    void f1() override {}
};

int main() {
    D d;
    E e;
    M m;
    (void)d;
    (void)e;
    (void)m;
    return 0;
}
