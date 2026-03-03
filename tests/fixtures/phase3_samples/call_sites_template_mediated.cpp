// Test fixture for template-mediated call tracking
// Tests: make_shared/make_unique with project types as template args

#include <memory>

class Sensor {
public:
    void read() {}
    Sensor() {}
    explicit Sensor(int id) : id_(id) {}
private:
    int id_ = 0;
};

class Widget {
public:
    void draw() {}
};

// Test: make_shared with project type
void factory_shared() {
    auto s = std::make_shared<Sensor>(42);
    s->read();
}

// Test: make_unique with project type
void factory_unique() {
    auto w = std::make_unique<Widget>();
    w->draw();
}

// Test: make_shared with primitive type (should NOT be template-mediated)
void factory_primitive() {
    auto p = std::make_shared<int>(42);
}

// Test: direct new (not template-mediated, just regular constructor)
void factory_direct() {
    std::unique_ptr<Sensor> p(new Sensor());
    p->read();
}
