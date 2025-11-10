// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;


import {SwapperOwnable, ISwapper} from "contracts/evk-periphery/Swaps/SwapperOwnable.sol";
import {SafeERC20Lib, IERC20} from "evk/EVault/shared/lib/SafeERC20Lib.sol";
import {GluexHandler} from "contracts/evk-periphery/Swaps/handlers/GluexHandler.sol";
import {IEVault} from "contracts/IEVault.sol";
import {IGsm} from "contracts/IGsm.sol";

contract GluexGsmSwapper is SwapperOwnable, GluexHandler {
    address public immutable gsm;

    bytes32 public constant HANDLER_GLUEX = bytes32("gluex");

    constructor(address _evc, address _owner, address _gluexRouter, address _gsm) SwapperOwnable(_evc, _owner, address(0), address(0)) GluexHandler(_gluexRouter) {
        gsm = _gsm;
    }

    /// @inheritdoc ISwapper
    function swap(SwapParams memory params) public virtual override(ISwapper, SwapperOwnable) externalLock {
        if (params.mode >= MODE_MAX_VALUE) revert Swapper_UnknownMode();

        if (params.handler == HANDLER_GLUEX) {
            swapGluex(params);
        } else {
            revert Swapper_UnknownHandler();
        }

        if (params.mode == MODE_EXACT_IN) return;

        // return unused input token after exact output swap
        _deposit(params.tokenIn, params.vaultIn, 0, params.accountIn);
    }

    /// @inheritdoc ISwapper
    function sweep(address token, uint256 amountMin, address to) public virtual override(ISwapper, SwapperOwnable) externalLock {
        // deposit underlying to gsm
        uint256 underlyingBalance = IERC20(IGsm(gsm).UNDERLYING_ASSET()).balanceOf(address(this));
        if (underlyingBalance > 0) {
            IGsm(gsm).sellAsset(underlyingBalance, address(this));
        }
        // sweep requested token balance
        uint256 balance = IERC20(token).balanceOf(address(this));
        if (balance >= amountMin) {
            SafeERC20Lib.safeTransfer(IERC20(token), to, balance);
        }
    }
}