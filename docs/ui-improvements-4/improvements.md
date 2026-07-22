# UI Improvements 4

## 1

![1](screenshots/UI/15.png)

For imported workflow parallel lanes (first lane on screenshot) may not have controls (duplicate, delete) at all. This lane even is not selectable as a lane. Lanes should be feature-equivalent to each other, look and behave the same.

May be similar problem exists in other blocks too: check all possible places and fix everywhere.

## 2

![2](screenshots/UI/2.png)

In the left menu sometimes scrollbar become very bold and don't disappear after scrolling. You should debug and fix. When you find the root cause check other elements for the same problem and fix.

## 3

![3](screenshots/UI/3.png)
![4](screenshots/UI/4.png)

Group card content overflows the card. May be find a better way to place content on card?

## 5

![5](screenshots/UI/5.png)

Left indentations are inconsistent between different blocks (screenshot). Check how inner content is spaced for all blocks and think how to make it consistent.

## 7

![7](screenshots/UI/7.png)

Expression help is hidden behind left menu (and even behind viewport). All similar components should be found and fixed. 

## 8

![8](screenshots/UI/8.png)

Constant creation form is inconsistent with constant edit form. In creation form there are no "unit" field, value feels like constant input in creation form, actually it is expression.

## 9

![9](screenshots/UI/9.png)

Form is broken. Find a way to fix.

## 10

![10](screenshots/UI/10.png)
![11](screenshots/UI/11.png)

Line separators introduced in PR #70 are looks terrible (rounded corners, inconsistent spacing, etc) see first screenshot. It should be implemented like it is done in file management menu (see second screenshot). It should be fixed everywhere!

## 12

![12](screenshots/UI/12.png)

A lot of expression inputs (may be all) are only 20px high instead of 24px as all other inputs (see screenshot). This issue should be found and fixed everywhere!

## 13

![13](screenshots/validation/13.png)
![14](screenshots/validation/14.png)

Expression validation does not work for bindings. Investigate this issue and fix everywhere!
