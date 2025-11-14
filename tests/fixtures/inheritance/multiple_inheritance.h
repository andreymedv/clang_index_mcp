#pragma once

class Base1 {
public:
    virtual ~Base1() {}
    virtual void method1() = 0;
};

class Base2 {
public:
    virtual ~Base2() {}
    virtual void method2() = 0;
};

class Derived : public Base1, public Base2 {
public:
    void method1() override;
    void method2() override;
    void derivedMethod();
};
