// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.26;

import {ISwapper} from "./ISwapper.sol";
import {SwapVerifier} from "./SwapVerifier.sol";
import {IEVC} from "./IEVC.sol";

import {IERC4626} from "./IEVault.sol";
import {IEVault} from "./IEVault.sol";
import {IBorrowing} from "./IEVault.sol";
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
    error LessThanExpectedCollateralReceived();

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
        address violatorAddress;
        address vault;
        address borrowedAsset;
        address collateralVault;
        address collateralAsset;
        uint256 repayAmount;
        uint256 seizedCollateralAmount;
        uint256 expectedRemainingCollateral;
        bytes swapData;
    }

    event Liquidation(
        address indexed violatorAddress,
        address indexed vault,
        address repaidBorrowAsset,
        address seizedCollateralAsset,
        uint256 amountRepaid,
        uint256 amountCollaterallSeized
    );

    function liquidate_single_collateral(
        LiquidationParams calldata params
    ) external returns (bool success) {
        bytes[] memory multicallItems = new bytes[](1);

        // Calls swap function of swapper which will swap some amount of seized collateral for borrowed asset
        // Sends received repayment token to swapper address (?) TODO: is this right?
        multicallItems[0] = abi.encodeCall(
            ISwapper.swap,
            ISwapper.SwapParams({
                handler: HANDLER_ONE_INCH,
                mode: 0,
                account: address(0), // ignored
                tokenIn: params.collateralAsset,
                tokenOut: params.borrowedAsset,
                amountOut: 0,
                vaultIn: address(0), // ignored
                receiver: address(0), // ignored
                data: params.swapData
            })
        );

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](6);
    
        // TODO: check if already enabled
        
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                IEVC.enableController,
                (
                    msg.sender,
                    params.vault
                )
            )
        });

        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                IEVC.enableCollateral,
                (
                    msg.sender,
                    params.collateralVault
                )
            )
        });

        // Step 3: Liquidate account in violation
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (
                    params.violatorAddress,
                    params.collateralAsset,
                    params.repayAmount,
                    params.seizedCollateralAmount
                )
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(
                IERC4626.withdraw,
                (
                    params.seizedCollateralAmount,
                    swapperAddress,
                    msg.sender
                )
            )
        });

        // Step 5: Swap collateral for borrowed asset
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        // Step 6: Repay debt
        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                IBorrowing.repay,
                (
                    params.repayAmount,
                    msg.sender
                )
            )
        });

        evc.batch(batchItems);

        // Check that the remaining collateral is as expected
        if(IEVault(params.collateralVault).convertToAssets(IEVault(params.collateralVault).balanceOf(address(this))) < params.expectedRemainingCollateral) {
            revert LessThanExpectedCollateralReceived();
        }

        emit Liquidation(
            params.violatorAddress,
            params.vault,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.seizedCollateralAmount
        );

        return true;
    }

    function liquidate_multiple_collaterals(
        LiquidationParams[] calldata paramsList
    ) external returns (bool success) {
        uint256 length = paramsList.length;

        bytes[] memory multicallItems = new bytes[](length);
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](length);

        uint256 totalRepayAmount;
        
        // TODO: think through the indexing logic for this
        for (uint256 i; i < length; ++i){
            LiquidationParams calldata params = paramsList[i];
            totalRepayAmount += params.repayAmount;

            multicallItems[i] = abi.encodeCall(
                ISwapper.swap,
                ISwapper.SwapParams({
                    handler: HANDLER_ONE_INCH,
                    mode: 0,
                    account: address(0), // ignored
                    tokenIn: params.collateralAsset,
                    tokenOut: params.borrowedAsset,
                    amountOut: 0,
                    vaultIn: address(0), // ignored
                    receiver: address(0), // ignored
                    data: params.swapData
                })
            );

            batchItems[i] = IEVC.BatchItem({
                onBehalfOfAccount: msg.sender,
                targetContract: params.vault,
                value: 0,
                data: abi.encodeCall(
                    IEVC.enableCollateral,
                    (
                        msg.sender,
                        params.collateralVault
                    )
                )
            });

            batchItems[i+1] = IEVC.BatchItem({
                onBehalfOfAccount: msg.sender,
                targetContract: params.vault,
                value: 0,
                data: abi.encodeCall(
                    ILiquidation.liquidate,
                    (
                        params.violatorAddress,
                        params.collateralAsset,
                        params.repayAmount,
                        params.seizedCollateralAmount
                    )
                )
            });

            batchItems[i+2] = IEVC.BatchItem({
                onBehalfOfAccount: msg.sender,
                targetContract: params.collateralVault,
                value: 0,
                data: abi.encodeCall(
                    IERC4626.withdraw,
                    (
                        params.seizedCollateralAmount,
                        swapperAddress,
                        msg.sender
                    )
                )
            });

            // Step 5: Swap collateral for borrowed asset
            batchItems[i+3] = IEVC.BatchItem({
                onBehalfOfAccount: msg.sender,
                targetContract: swapperAddress,
                value: 0,
                data: abi.encodeCall(ISwapper.multicall, multicallItems)
            });
        }

        // First step: enable controller
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: paramsList[0].vault,
            value: 0,
            data: abi.encodeCall(
                IEVC.enableController,
                (
                    msg.sender,
                    paramsList[0].vault
                )
            )
        });

        // Last step: Repay debt
         batchItems[length - 1] = IEVC.BatchItem({
            onBehalfOfAccount: msg.sender,
            targetContract: paramsList[0].vault,
            value: 0,
            data: abi.encodeCall(
                IBorrowing.repay,
                (
                    totalRepayAmount,
                    msg.sender
                )
            )
        });

        evc.batch(batchItems);

        for (uint256 i; i < length; ++i){
            LiquidationParams calldata params = paramsList[i];

            // Check that the remaining collateral is as expected
            if(IEVault(params.collateralVault).convertToAssets(IEVault(params.collateralVault).balanceOf(address(this))) < params.expectedRemainingCollateral) {
                revert LessThanExpectedCollateralReceived();
            }

            emit Liquidation(
                params.violatorAddress,
                params.vault,
                params.borrowedAsset,
                params.collateralAsset,
                params.repayAmount,
                params.seizedCollateralAmount
            );
        }

        return true;
    }
}
