#pragma once
struct MockSPI { void begin(int,int,int,int) {} };
inline MockSPI SPI;
