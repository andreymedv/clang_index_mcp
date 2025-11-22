#pragma once

class GrandParent {
public:
    virtual ~GrandParent() {}
    virtual void grandParentMethod();

protected:
    int grandParentValue_;
};

class Parent : public GrandParent {
public:
    void grandParentMethod() override;
    virtual void parentMethod();

protected:
    int parentValue_;
};

class Child : public Parent {
public:
    void parentMethod() override;
    void childMethod();

protected:
    int childValue_;
};

class GrandChild : public Child {
public:
    void grandChildMethod();

private:
    int grandChildValue_;
};
