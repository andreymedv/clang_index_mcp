#pragma once

class Base {
public:
    Base();
    virtual ~Base();

    virtual void virtualMethod();
    void baseMethod();

protected:
    int baseValue_;
};

class Derived : public Base {
public:
    Derived();
    ~Derived();

    void virtualMethod() override;
    void derivedMethod();

private:
    int derivedValue_;
};
