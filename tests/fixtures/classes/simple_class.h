#pragma once

class SimpleClass {
public:
    SimpleClass();
    ~SimpleClass();

    void doSomething();
    int getValue() const;

private:
    int value_;
};
