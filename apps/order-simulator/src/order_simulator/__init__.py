"""External Order System — simulator.

A small, separate application that owns customer orders for the demo. It is not Square, not a
production point of sale and not a real customer system; it is a stand-in that exists so an
order can be changed outside PromisePatch and the change can be watched arriving.

It shares no database, no models and no code with PromisePatch. The only thing between them is
the `order_contract` distribution and two HTTP calls.
"""
