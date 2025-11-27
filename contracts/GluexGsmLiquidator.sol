// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Liquidator} from "./Liquidator.sol";

contract GluexGsmLiquidator is Liquidator {
    constructor(
        address _owner,
        address _gluexGsmSwapperAddress,
        address _swapVerifierAddress,
        address _evcAddress,
        address _pythAddress
    ) Liquidator(_owner, _gluexGsmSwapperAddress, _swapVerifierAddress, _evcAddress, _pythAddress) {}
}
