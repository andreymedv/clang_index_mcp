// Interface
class IInterface {
public:
    virtual void execute() = 0;
};

// CRTP-like base that inherits from template parameter
template<typename Interface>
class ImplementationBase : public Interface {
public:
    void commonLogic() { }
};

// Concrete class derived from template specialization
class ConcreteImpl : public ImplementationBase<IInterface> {
public:
    void execute() override { }
};

// Another variation
class IAnotherInterface {
public:
    virtual void process() = 0;
};

class AnotherImpl : public ImplementationBase<IAnotherInterface> {
public:
    void process() override { }
};
