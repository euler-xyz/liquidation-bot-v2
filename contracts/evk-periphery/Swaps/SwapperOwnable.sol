// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.0;

import {Ownable, Context} from "openzeppelin-contracts/access/Ownable.sol";
import {EVCUtil} from "ethereum-vault-connector/utils/EVCUtil.sol";
import {Swapper} from "lib/evk-periphery/src/Swaps/Swapper.sol";
import {ISwapper} from "lib/evk-periphery/src/Swaps/ISwapper.sol";

/// @title SwapperOwnable
/// @custom:security-contact security@euler.xyz
/// @author Euler Labs (https://www.eulerlabs.com/)
/// @notice Untrusted helper contract for EVK for performing swaps and swaps to repay. Ownable version.
contract SwapperOwnable is Swapper, EVCUtil, Ownable {
    modifier onlyOwnerOrSelf() {
        if (msg.sender != address(this)) _checkOwner();
        _;
    }

    constructor(address evc, address owner, address uniswapRouterV2, address uniswapRouterV3)
        Swapper(uniswapRouterV2, uniswapRouterV3)
        EVCUtil(evc)
        Ownable(owner)
    {}

    /// @inheritdoc ISwapper
    function swap(SwapParams memory params) public virtual override onlyOwnerOrSelf {
        super.swap(params);
    }

    /// @inheritdoc ISwapper
    function repay(address token, address vault, uint256 repayAmount, address account)
        public
        virtual
        override
        onlyOwnerOrSelf
    {
        super.repay(token, vault, repayAmount, account);
    }

    /// @inheritdoc ISwapper
    function repayAndDeposit(address token, address vault, uint256 repayAmount, address account)
        public
        virtual
        override
        onlyOwnerOrSelf
    {
        super.repayAndDeposit(token, vault, repayAmount, account);
    }

    /// @inheritdoc ISwapper
    function deposit(address token, address vault, uint256 amountMin, address account)
        public
        virtual
        override
        onlyOwnerOrSelf
    {
        super.deposit(token, vault, amountMin, account);
    }

    /// @inheritdoc ISwapper
    function sweep(address token, uint256 amountMin, address to) public virtual override onlyOwnerOrSelf {
        super.sweep(token, amountMin, to);
    }

    /// @inheritdoc ISwapper
    function multicall(bytes[] memory calls) public virtual override onlyOwner {
        super.multicall(calls);
    }

    function _msgSender() internal view override (Context, EVCUtil) returns (address) {
        return EVCUtil._msgSender();
    }
}
