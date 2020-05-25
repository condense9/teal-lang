# The Teal Programming Language

![Tests](https://github.com/condense9/teal-lang/workflows/Build/badge.svg?branch=master) [![PyPI](https://badge.fury.io/py/teal-lang.svg)](https://pypi.org/project/teal-lang) [![Gitter](https://badges.gitter.im/Teal-Lang/community.svg)](https://gitter.im/Teal-Lang/community?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge)

Teal is a programming language for serverless cloud applications, designed for
passing data around between functions. Concurrency supported. Execution tracing
built-in.

These things are important to Teal:
- *really fast development* with **easy local testing**, and no coupling between
  application and infrastructure.
- cheap deployments, because **everything is serverless** and there is no
  orchestrator to run idle.
- built-in **tracing/profiling**, so it's easy to know what's happening in your
  workflows.
  
Teal functions run natively on AWS Lambda and can be suspended to wait until
other functions finish. Execution data is stored in DynamoDB.

![Concurrency](doc/functions.png)

Documentation coming soon! For now, browse the [the examples](test/examples) or
the check out the [Teal Playground](https://www.condense9.com/playground).


## Getting started

**Teal is alpha quality - don't use it for mission critical things.**

```shell
$ pip install teal-lang
```

This gives you the `teal` executable.

Browse the [the examples](test/examples) to explore the syntax.

Check out an [example AWS deployment](examples/hello/serverless.yml) using the
Serverless Framework.

[Create an issue](https://github.com/condense9/teal-lang/issues) if none of this
makes sense, or you'd like help getting started.


### Teal May Not Be For You!

Teal *is* for you if:
- you want to build ETL pipelines *really quickly*.
- you have a repository of data processing scripts, and want to connect them
  together in the cloud.
- you insist on being able to test as much as possible locally.
- You don't have time (or inclination) to deploy and manage a full-blown
  platform (Spark, Airflow, etc).
- You're wary of Step Functions (and similar) because of vendor lock-in and cost.

Core principles guiding Teal design:
- Do the heavy-lifting in Python.
- Keep business logic out of infrastructure (no more hard-to-test logic defined
  in IaC, please).
- Workflows must be fully tested locally before deployment.


## Why Teal?

Teal is **not** Kubernetes, because it's not trying to let you easily scale
Dockerised services.

Teal is **not** containerisation, because.. well because there are no containers
here.

Teal is **not** a general-purpose programming language, because that would be
needlessly reinventing the wheel.

Teal is a very simple compiled language with only a few constructs:

1. named variables (data, functions)
2. `async`/`await` concurrency primitives 
3. Python (>=3.8) interop
4. A few basic types

Two interpreters have been implemented so far -- local and AWS Lambda, but
there's no reason Teal couldn't run on top of (for example) Kubernetes. [Issue
#8](https://github.com/condense9/teal-lang/issues/8)

**Concurrency**: Teal gives you "bare-metal concurrency" (i.e. without external
coordination) on top of AWS Lambda.

When you do `y = async f(x)`, Teal computes `f(x)` on a new Lambda instance. And
then when you do `await y`, the current Lambda function terminates, and
automatically continues when `y` is finished being computed. There's no idle
server time.

**Testing**: The local interpreter lets you test your program before deployment,
and uses Python threading for concurrency.

**Tracing and profiling**: Teal has a built-in tracer tool, so it's easy to see
where the time is going.


## Current Limitations and Roadmap

Teal is alpha quality, which means that it's not thoroughly tested, and lots of
breaking changes are planned. This is a non-exhaustive list.

### Libraries

Only one Teal program file is supported, but a module/package system is
[planned](https://github.com/condense9/teal-lang/issues/9).

### Error Handling

There's no error handling - if your function fails, you'll have to restart the
whole process manually. An exception handling system is
[planned](https://github.com/condense9/teal-lang/issues/1).

### Typing

Function inputs and outputs aren't typed. This is a limitation, and will be
fixed soon, probably using
[ProtoBufs](https://developers.google.com/protocol-buffers/) as the interface
definition language.

### Calling Arbitrary Services

Currently you can only call Teal or Python functions -- arbitrary microservices
can't be called. Before Teal v1.0 is released, this will be possible. You will
be able to call a long-running third party service (e.g. an AWS ML service) as a
normal Teal function and `await` on the result.

### Dictionary (associative map) primitives

Teal really should be able to natively manipulate JSON objects. This may happen
before v1.0.

---


## Contributing

Contributions of any form are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md)


## Who?

Teal is maintained by [Condense9 Ltd.](https://www.condense9.com/), which is
really [one guy](https://www.linkedin.com/in/rmhsilva/) who loves maths and
programming languages.

Teal started because he couldn't find any data engineering tools that were
productive and *felt* like software engineering. As an industry, we've spent
decades growing a wealth of computer science knowledge, and building data
pipelines in $IaC, or manually crafting workflow DAGs with $AutomationTool, just
isn't software.


## License

Apache License (Version 2.0). See [LICENSE](LICENSE) for details.
