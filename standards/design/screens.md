---
domain: design
tags: [screens, states, layout, interactions, copy, platforms]
applies_to: [web, mobile, any]
---

# Screens

How every screen in this project is decided, before a line of UI is written. The Designer
writes against these; the Web and Mobile specialists build what the Designer wrote.

## Every screen says what it is for

One sentence, in the words of the person using it — "pick the class you are in", not
"class selection component". A screen whose purpose cannot be said in one sentence is
two screens.

## States are part of the design, not an afterthought

Every screen that loads something has a loading state and an empty state. Every screen
that saves something has a failure state that says what to do next. A list that can be
empty is designed empty first: an empty list with no words in it is a bug that ships.

## The same product on both platforms

Web and mobile share the vocabulary, the order of the steps and the words on the buttons.
They do not share the layout: a phone screen is one column and a thumb's reach, a browser
window is not. Where both build the same screen, design it once and say `both`.

## Words are design

Button labels say what happens ("Sınıfı seç", not "Tamam"). Errors say what went wrong and
what to do. Nothing in the interface is named after the code behind it.

## What is not decided here

Colour values, fonts, spacing scales and component libraries belong to the stack the
Architect chose. The design says "the score dominates the result screen", not "32px bold".
