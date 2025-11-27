// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.0;

import {BaseHandler} from "lib/evk-periphery/src/Swaps/handlers/BaseHandler.sol";

/// @title GluexHandler
/// @custom:security-contact security@euler.xyz
/// @author Last Labs
/// @notice Swap handler executing swaps on GlueX
abstract contract GluexHandler is BaseHandler {
    address public immutable gluexRouter;

    error GluexHandler_InvalidSwapData();

    constructor(address _gluexRouter) {
        gluexRouter = _gluexRouter;
    }

    function swapGluex(SwapParams memory params) internal virtual {
        if (params.data.length == 0) revert GluexHandler_InvalidSwapData();

        setMaxAllowance(params.tokenIn, gluexRouter);

        (bool success, bytes memory result) = gluexRouter.call(
            params.data
        );
        if (!success || (result.length == 0 && gluexRouter.code.length == 0)) {
            revert Swapper_SwapError(gluexRouter, result);
        }

        setZeroAllowance(params.tokenIn, gluexRouter);
    }

    function setZeroAllowance(address token, address spender) internal {
        safeApproveWithRetry(token, spender, 0);
    }
}
