// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.26;

import {ISwapper} from "./ISwapper.sol";
import {SwapVerifier} from "./SwapVerifier.sol";
import {IEVC} from "./IEVC.sol";

import {IERC4626} from "./IEVault.sol";
import {IEVault} from "./IEVault.sol";
import {ILiquidation} from "./IEVault.sol";

contract Liquidator {
    address public immutable owner;
    address public immutable swapperAddress;
    address public immutable swapVerifierAddress;
    address public immutable evcAddress;

    bytes32 public constant HANDLER_ONE_INCH = bytes32("1Inch");
    bytes32 public constant HANDLER_UNISWAP_V2 = bytes32("UniswapV2");
    bytes32 public constant HANDLER_UNISWAP_V3 = bytes32("UniswapV3");
    bytes32 public constant HANDLER_UNISWAP_AUTOROUTER =
        bytes32("UniswapAutoRouter");

    ISwapper swapper;
    IEVC evc;

    error Unauthorized();

    constructor(
        address _swapperAddress,
        address _swapVerifierAddress,
        address _evcAddress
    ) {
        owner = msg.sender;
        swapperAddress = _swapperAddress;
        swapVerifierAddress = _swapVerifierAddress;
        evcAddress = _evcAddress;

        swapper = ISwapper(_swapperAddress);
        evc = IEVC(_evcAddress);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Unauthorized");
        _;
    }

    struct LiquidationParams {
        address vaultAddress;
        address violatorAddress;
        address borrowedAsset;
        address collateralAsset;
        uint256 repayAmount;
        uint256 expectedCollateralAmount;
        bytes swapData;
    }

    event Liquidation(
        address indexed vaultAddress,
        address indexed violatorAddress,
        address repaidBorrowAsset,
        address seizedCollateralAsset,
        uint256 amountRepaid,
        uint256 amountCollaterallSeized
    );

    function liquidate(
        LiquidationParams calldata params
    ) external onlyOwner returns (bool success) {
        bytes[] memory multicallItems = new bytes[](1); // for now just doing single swap, but setting up to handle multiple down the line

        // enable collateral and controller for liquidation
        evc.enableCollateral(msg.sender, params.collateralAsset);
        evc.enableController(msg.sender, params.vaultAddress);

        // TODO: use swapper in correct way
        // TODO: correctly use evc account instead of msg.sender
        multicallItems[0] = abi.encodeCall(
            ISwapper.swap,
            ISwapper.SwapParams({
                handler: HANDLER_ONE_INCH,
                mode: 2,
                account: params.violatorAddress,
                tokenIn: params.borrowedAsset,
                tokenOut: params.collateralAsset,
                vaultIn: params.vaultAddress,
                receiver: params.vaultAddress,
                amountOut: 0,
                data: injectReceiver(swapperAddress, params.swapData)
            })
        );

        IEVC.BatchItem[] memory items = new IEVC.BatchItem[](4);

        // TODO: get the ordering of these correct
        items[0] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.vaultAddress,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (
                    params.violatorAddress,
                    params.collateralAsset,
                    params.repayAmount,
                    params.expectedCollateralAmount
                )
            )
        });

        items[1] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.vaultAddress,
            value: 0,
            data: abi.encodeCall(
                IERC4626.withdraw,
                (
                    params.expectedCollateralAmount,
                    swapperAddress,
                    msg.sender
                )
            )
        });

        items[2] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        items[3] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: swapVerifierAddress,
            value: 0,
            data: abi.encodeCall(
                SwapVerifier.verifyDebtMax,
                (
                    params.vaultAddress,
                    msg.sender,
                    0,
                    type(uint256).max
                )
            )
        });

        evc.batch(items);

        emit Liquidation(
            params.vaultAddress,
            params.violatorAddress,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.expectedCollateralAmount
        );

        return true;
    }

    // Need to understand this more
    function injectReceiver(address receiver, bytes memory _payload) internal pure returns (bytes memory payload) {
        payload = _payload;

        // uint256 constant RECEIVER_OFFSET = 208;

        assembly {
            mstore(0, receiver)
            mcopy(add(add(payload, 32), 208), 12, 20)
        }
    }
}
