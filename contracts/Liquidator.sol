// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.26;

import {ISwapper} from "./ISwapper.sol";
import {SwapVerifier} from "./SwapVerifier.sol";
import {IEVC} from "./IEVC.sol";

import {IERC4626, IERC20} from "./IEVault.sol";
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
        uint256 swapAmount;
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

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](7);
    
        // TODO: check if already enabled
        
        // Step 1: enable controller
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(
                IEVC.enableController,
                (
                    address(this),
                    params.vault
                )
            )
        });
        
        // Step 2: enable collateral
        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(
                IEVC.enableCollateral,
                (
                    address(this),
                    params.collateralVault
                )
            )
        });

        // Step 3: Liquidate account in violation
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (
                    params.violatorAddress,
                    params.collateralVault,
                    params.repayAmount,
                    params.seizedCollateralAmount
                )
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(
                IERC4626.withdraw,
                (
                    params.swapAmount,
                    swapperAddress,
                    address(this)
                )
            )
        });

        // Step 5: Swap collateral for borrowed asset
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        // Step 6: call swap verifier
        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: address(swapVerifierAddress),
            value: 0,
            data: abi.encodeCall(SwapVerifier.verifyAmountMinAndSkim, (params.vault, address(this), 1, type(uint256).max))
        });

        // Step 7: repay debt
        batchItems[6] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                IBorrowing.repay,
                (
                    params.repayAmount,
                    address(this)
                )
            )
        });

        // Step 8: TODO: transfer leftover position to an account owned by an EOA

        evc.batch(batchItems);

        // // Check that the remaining collateral is as expected
        // if(IEVault(params.collateralVault).convertToAssets(IEVault(params.collateralVault).balanceOf(address(this))) < params.expectedRemainingCollateral) {
        //     revert LessThanExpectedCollateralReceived();
        // }

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
}
