import pytest
import pythonmonkey as pm
import asyncio

def test_set_clear_timeout():
    # throw RuntimeError outside a coroutine
    with pytest.raises(RuntimeError, match="PythonMonkey cannot find a running Python event-loop to make asynchronous calls."):
        pm.eval("setTimeout")(print)

    async def async_fn():
        # standalone `setTimeout`
        loop = asyncio.get_running_loop()
        f0 = loop.create_future()
        def add(a, b, c):
          f0.set_result(a + b + c)
        pm.eval("setTimeout")(add, 0, 1, 2, 3)
        assert 6.0 == await f0

        # test `clearTimeout`
        f1 = loop.create_future()
        def to_raise(msg):
            f1.set_exception(TypeError(msg))
        timeout_id0 = pm.eval("setTimeout")(to_raise, 100, "going to be there")
        assert type(timeout_id0) == float
        assert timeout_id0 > 0                  # `setTimeout` should return a positive integer value
        assert int(timeout_id0) == timeout_id0
        with pytest.raises(TypeError, match="going to be there"):
            await f1                                # `clearTimeout` not called
        f1 = loop.create_future()
        timeout_id1 = pm.eval("setTimeout")(to_raise, 100, "shouldn't be here")
        pm.eval("clearTimeout")(timeout_id1)
        with pytest.raises(asyncio.exceptions.TimeoutError):
            await asyncio.wait_for(f1, timeout=0.5) # `clearTimeout` is called

        # `this` value in `setTimeout` callback should be the global object, as spec-ed
        assert await pm.eval("new Promise(function (resolve) { setTimeout(function(){ resolve(this == globalThis) }) })")
        # `setTimeout` should allow passing additional arguments to the callback, as spec-ed
        assert 3.0 == await pm.eval("new Promise((resolve) => setTimeout(function(){ resolve(arguments.length) }, 100, 90, 91, 92))")
        assert 92.0 == await pm.eval("new Promise((resolve) => setTimeout((...args) => { resolve(args[2]) }, 100, 90, 91, 92))")
        # TODO (Tom Tang): test `setTimeout` setting delay to 0 if < 0
        # TODO (Tom Tang): test `setTimeout` accepting string as the delay, coercing to a number like parseFloat

        # passing an invalid ID to `clearTimeout` should silently do nothing; no exception is thrown.
        pm.eval("clearTimeout(NaN)")
        pm.eval("clearTimeout(999)")
        pm.eval("clearTimeout(-1)")
        pm.eval("clearTimeout('a')")
        pm.eval("clearTimeout(undefined)")
        pm.eval("clearTimeout()")

        # passing a `code` string to `setTimeout` as the callback function
        assert "code string" == await pm.eval("""
        new Promise((resolve) => {
            globalThis._resolve = resolve
            setTimeout("globalThis._resolve('code string'); delete globalThis._resolve", 100)
        })
        """)

        # making sure the async_fn is run
        return True
    assert asyncio.run(async_fn())

    # throw RuntimeError outside a coroutine (the event-loop has ended)
    with pytest.raises(RuntimeError, match="PythonMonkey cannot find a running Python event-loop to make asynchronous calls."):
        pm.eval("setTimeout")(print)

def test_promises():
    # should throw RuntimeError if Promises are created outside a coroutine
    create_promise = pm.eval("() => Promise.resolve(1)")
    with pytest.raises(RuntimeError, match="PythonMonkey cannot find a running Python event-loop to make asynchronous calls."):
        create_promise()

    async def async_fn():
        create_promise() # inside a coroutine, no error

        # Python awaitables to JS Promise coercion
        # 1. Python asyncio.Future to JS promise
        loop = asyncio.get_running_loop()
        f0 = loop.create_future()
        f0.set_result(2561)
        assert type(f0) == asyncio.Future
        assert 2561 == await f0
        assert pm.eval("(p) => p instanceof Promise")(f0) is True
        assert 2561 == await pm.eval("(p) => p")(f0)
        del f0

        # 2. Python asyncio.Task to JS promise
        async def coro_fn(x):
            await asyncio.sleep(0.01)
            return x
        task = loop.create_task(coro_fn("from a Task"))
        assert type(task) == asyncio.Task
        assert type(task) != asyncio.Future
        assert isinstance(task, asyncio.Future)
        assert "from a Task" == await task
        assert pm.eval("(p) => p instanceof Promise")(task) is True
        assert "from a Task" == await pm.eval("(p) => p")(task)
        del task

        # 3. Python coroutine to JS promise
        coro = coro_fn("from a Coroutine")
        assert asyncio.iscoroutine(coro)
        # assert "a Coroutine" == await coro                            # coroutines cannot be awaited more than once
        # assert pm.eval("(p) => p instanceof Promise")(coro) is True   #   RuntimeError: cannot reuse already awaited coroutine
        assert "from a Coroutine" == await pm.eval("(p) => (p instanceof Promise) && p")(coro)
        del coro

        # JS Promise to Python awaitable coercion
        assert 100 == await pm.eval("new Promise((r)=>{ r(100) })")
        assert 10010 == await pm.eval("Promise.resolve(10010)")
        with pytest.raises(pm.SpiderMonkeyError, match="^TypeError: (.|\\n)+ is not a constructor$"):
            await pm.eval("Promise.resolve")(10086)
        assert 10086 == await pm.eval("Promise.resolve.bind(Promise)")(10086)

        assert "promise returning a function" == (await pm.eval("Promise.resolve(() => { return 'promise returning a function' })"))()
        assert "function 2" == (await pm.eval("Promise.resolve(x=>x)"))("function 2")
        def aaa(n):
            return n
        ident0 = await (pm.eval("Promise.resolve.bind(Promise)")(aaa))
        assert "from aaa" == ident0("from aaa")
        ident1 = await pm.eval("async (aaa) => x=>aaa(x)")(aaa)
        assert "from ident1" == ident1("from ident1")
        ident2 = await pm.eval("() => Promise.resolve(x=>x)")()
        assert "from ident2" == ident2("from ident2")
        ident3 = await pm.eval("(aaa) => Promise.resolve(x=>aaa(x))")(aaa)
        assert "from ident3" == ident3("from ident3")
        del aaa

        # promise returning a JS Promise<Function> that calls a Python function inside
        def fn0(n):
            return n + 100
        def fn1():
            return pm.eval("async x=>x")(fn0)
        fn2 = await pm.eval("async (fn1) => { const fn0 = await fn1(); return Promise.resolve(x=>fn0(x)) }")(fn1)
        assert 101.2 == fn2(1.2)
        fn3 = await pm.eval("async (fn1) => { const fn0 = await fn1(); return Promise.resolve(async x => { return fn0(x) }) }")(fn1)
        assert 101.3 == await fn3(1.3)
        fn4 = await pm.eval("async (fn1) => { return Promise.resolve(async x => { const fn0 = await fn1(); return fn0(x) }) }")(fn1)
        assert 101.4 == await fn4(1.4)
        
        # chained JS promises
        assert "chained" == await (pm.eval("async () => new Promise((resolve) => resolve( Promise.resolve().then(()=>'chained') ))")())

        # chained Python awaitables
        async def a():
            await asyncio.sleep(0.01)
            return "nested"
        async def b():
            await asyncio.sleep(0.01)
            return a()
        async def c():
            await asyncio.sleep(0.01)
            return b()
        # JS `await` supports chaining. However, on Python-land, it actually requires `await (await (await c()))`
        assert "nested" == await pm.eval("async (promise) => await promise")(c())
        assert "nested" == await pm.eval("async (promise) => await promise")(await c())
        assert "nested" == await pm.eval("async (promise) => await promise")(await (await c()))
        assert "nested" == await pm.eval("async (promise) => await promise")(await (await (await c())))
        assert "nested" == await pm.eval("async (promise) => promise")(c())
        assert "nested" == await pm.eval("async (promise) => promise")(await c())
        assert "nested" == await pm.eval("async (promise) => promise")(await (await c()))
        assert "nested" == await pm.eval("async (promise) => promise")(await (await (await c())))
        assert "nested" == await pm.eval("(promise) => Promise.resolve(promise)")(c())
        assert "nested" == await pm.eval("(promise) => Promise.resolve(promise)")(await c())
        assert "nested" == await pm.eval("(promise) => Promise.resolve(promise)")(await (await c()))
        assert "nested" == await pm.eval("(promise) => Promise.resolve(promise)")(await (await (await c())))
        assert "nested" == await pm.eval("(promise) => promise")(c())
        assert "nested" == await pm.eval("(promise) => promise")(await c())
        assert "nested" == await pm.eval("(promise) => promise")(await (await c()))
        with pytest.raises(TypeError, match="object str can't be used in 'await' expression"):
            await pm.eval("(promise) => promise")(await (await (await c())))

        # Python awaitable throwing exceptions
        async def coro_to_throw0():
            await asyncio.sleep(0.01)
            print([].non_exist) # type: ignore
        with pytest.raises(pm.SpiderMonkeyError, match="Python AttributeError: 'list' object has no attribute 'non_exist'"):
            await (pm.eval("(promise) => promise")(coro_to_throw0()))
        with pytest.raises(pm.SpiderMonkeyError, match="Python AttributeError: 'list' object has no attribute 'non_exist'"):
            await (pm.eval("async (promise) => promise")(coro_to_throw0()))
        with pytest.raises(pm.SpiderMonkeyError, match="Python AttributeError: 'list' object has no attribute 'non_exist'"):
            await (pm.eval("(promise) => Promise.resolve().then(async () => await promise)")(coro_to_throw0()))
        async def coro_to_throw1():
            await asyncio.sleep(0.01)
            raise TypeError("reason")
        with pytest.raises(pm.SpiderMonkeyError, match="Python TypeError: reason"):
            await (pm.eval("(promise) => promise")(coro_to_throw1()))
        assert 'rejected <Python TypeError: reason>' == await pm.eval("(promise) => promise.then(()=>{}, (err)=>`rejected <${err.message}>`)")(coro_to_throw1())

        # JS Promise throwing exceptions
        with pytest.raises(pm.SpiderMonkeyError, match="nan"):
            await pm.eval("Promise.reject(NaN)") # JS can throw anything
        with pytest.raises(pm.SpiderMonkeyError, match="123.0"):
            await (pm.eval("async () => { throw 123 }")())
            # await (pm.eval("async () => { throw {} }")())
        with pytest.raises(pm.SpiderMonkeyError, match="anything"):
            await pm.eval("Promise.resolve().then(()=>{ throw 'anything' })")
            # FIXME (Tom Tang): We currently handle Promise exceptions by converting the object thrown to a Python Exception object through `pyTypeFactory`
            #               <objects of this type are not handled by PythonMonkey yet>
            # await pm.eval("Promise.resolve().then(()=>{ throw {a:1,toString(){return'anything'}} })")
        with pytest.raises(pm.SpiderMonkeyError, match="on line 1:\nTypeError: undefined has no properties"): # not going through the conversion
            await pm.eval("Promise.resolve().then(()=>{ (undefined).prop })")

        # TODO (Tom Tang): Modify this testcase once we support ES2020-style dynamic import
        # pm.eval("import('some_module')") # dynamic import returns a Promise, see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import
        with pytest.raises(pm.SpiderMonkeyError, match="\nError: Dynamic module import is disabled or not supported in this context"):
            await pm.eval("import('some_module')")
        # TODO (Tom Tang): properly test unhandled rejection

        # await scheduled jobs on the Python event-loop
        js_sleep = pm.eval("(second) => new Promise((resolve) => setTimeout(resolve, second*1000))")
        def py_sleep(second): # asyncio.sleep has issues on Python 3.8
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            loop.call_later(second, lambda:future.set_result(None))
            return future
        both_sleep = pm.eval("(js_sleep, py_sleep) => async (second) => { await js_sleep(second); await py_sleep(second) }")(js_sleep, py_sleep)
        await asyncio.wait_for(both_sleep(0.1), timeout=0.3) # won't be precisely 0.2s 
        with pytest.raises(asyncio.exceptions.TimeoutError):
            await asyncio.wait_for(both_sleep(0.1), timeout=0.19)

        # making sure the async_fn is run
        return True
    assert asyncio.run(async_fn())

    # should throw a RuntimeError if created outside a coroutine (the event-loop has ended)
    with pytest.raises(RuntimeError, match="PythonMonkey cannot find a running Python event-loop to make asynchronous calls."):
        pm.eval("new Promise(() => { })")

# off-thread promises
def test_webassembly():
    async def async_fn():
        # off-thread promises can run
        assert 'instantiated' == await pm.eval("""
        // https://github.com/mdn/webassembly-examples/blob/main/js-api-examples/simple.wasm
        var code = new Uint8Array([
            0,  97, 115, 109,   1,   0,   0,   0,   1,   8,   2,  96,
            1, 127,   0,  96,   0,   0,   2,  25,   1,   7, 105, 109,
        112, 111, 114, 116, 115,  13, 105, 109, 112, 111, 114, 116,
        101, 100,  95, 102, 117, 110,  99,   0,   0,   3,   2,   1,
            1,   7,  17,   1,  13, 101, 120, 112, 111, 114, 116, 101,
        100,  95, 102, 117, 110,  99,   0,   1,  10,   8,   1,   6,
            0,  65,  42,  16,   0,  11
        ]);

        WebAssembly.instantiate(code, { imports: { imported_func() {} } }).then(() => 'instantiated')
        """)

        # making sure the async_fn is run
        return True
    assert asyncio.run(async_fn())
